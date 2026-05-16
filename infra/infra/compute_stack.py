"""
infra/compute_stack.py

EC2 + Elastic IP + IAM role + user-data bootstrap.

This is the stack that costs real money. ~$9.30/mo at 24/7:
    t3.micro     ~$8.50  (no longer free under the 2025 Free Plan)
    EIP attached  $0.00  (only billed when *unattached*, $3.60/mo)
    8 GB gp3      ~$0.64
    egress        ~$0.20

Strategy: leave it running ONLY when actively demoing. `destroy.sh`
puts the cost back to ~$0 in 2 minutes.

User data does the minimum needed to make `docker compose` runnable:
    - Docker Engine + Compose v2 plugin
    - CloudWatch Agent reporting CPU/mem/disk to MindMarket/EC2 namespace
    - cloud-init log shipped to /mindmarket/ec2/cloud-init log group
    - SSM agent (already in AL2023) for Session Manager fallback

It does NOT clone the repo or start the app. That's `deploy-phase-1.sh`'s
job — separating bootstrap (rare, slow, baked-in) from app deploy
(frequent, fast, scriptable) keeps iteration tight.
"""

from __future__ import annotations

from aws_cdk import (
    CfnOutput,
    Stack,
)
from aws_cdk import (
    aws_ec2 as ec2,
)
from aws_cdk import (
    aws_iam as iam,
)
from constructs import Construct

from infra.foundation_stack import FoundationStack

# Multi-line strings that go into AWS APIs MUST be ASCII-only.
# Lesson learned the hard way in commit 22745cb.
USER_DATA_SH = r"""#!/bin/bash
set -euxo pipefail

LOG=/var/log/mindmarket-bootstrap.log
exec > >(tee -a "$LOG") 2>&1
echo "==> bootstrap started $(date -u)"

# AL2023 uses dnf
dnf update -y
dnf install -y docker git amazon-cloudwatch-agent

# Docker Compose v2 plugin + Buildx (neither in default AL2023 repos).
# Compose v2.31+ requires buildx 0.17+ at build time; AL2023's bundled
# buildx is 0.12, so the build step fails with
#   "compose build requires buildx 0.17.0 or later"
# unless we install a fresh one alongside compose.
mkdir -p /usr/libexec/docker/cli-plugins
ARCH=$(uname -m)
case "$ARCH" in
  x86_64)
    COMPOSE_BIN="docker-compose-linux-x86_64"
    BUILDX_BIN="buildx-v0.18.0.linux-amd64"
    ;;
  aarch64)
    COMPOSE_BIN="docker-compose-linux-aarch64"
    BUILDX_BIN="buildx-v0.18.0.linux-arm64"
    ;;
  *) echo "Unsupported arch: $ARCH"; exit 1 ;;
esac
curl -fsSL "https://github.com/docker/compose/releases/latest/download/${COMPOSE_BIN}" \
  -o /usr/libexec/docker/cli-plugins/docker-compose
curl -fsSL "https://github.com/docker/buildx/releases/download/v0.18.0/${BUILDX_BIN}" \
  -o /usr/libexec/docker/cli-plugins/docker-buildx
chmod +x /usr/libexec/docker/cli-plugins/docker-compose
chmod +x /usr/libexec/docker/cli-plugins/docker-buildx

# Allow ec2-user to talk to docker without sudo
usermod -aG docker ec2-user
systemctl enable --now docker

# CloudWatch Agent: minimal Phase 1 config
# (Phase 3 ADR will expand this to dashboards + alarms.)
cat > /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json <<'CWAGENT'
{
  "agent": {"metrics_collection_interval": 60},
  "metrics": {
    "namespace": "MindMarket/EC2",
    "metrics_collected": {
      "cpu":  {"resources": ["*"], "measurement": ["usage_active", "usage_idle"], "totalcpu": true},
      "mem":  {"measurement": ["mem_used_percent", "mem_available_percent"]},
      "disk": {"resources": ["/"], "measurement": ["used_percent", "inodes_free"]}
    }
  },
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {"file_path": "/var/log/mindmarket-bootstrap.log",
           "log_group_name": "/mindmarket/ec2/bootstrap",
           "log_stream_name": "{instance_id}",
           "retention_in_days": 7}
        ]
      }
    }
  }
}
CWAGENT
systemctl enable --now amazon-cloudwatch-agent
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config -m ec2 -s \
  -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json

# 1 GB swap file. Without this, t3.micro's 1 GB RAM is exhausted by
# `pip install scipy + pandas + supabase + ...` during `docker compose
# build`, the OOM killer takes out random processes, and the whole
# instance wedges. Verified live: rebuild took ~10 min on first try
# (with swap) where it was OOM-wedging in <5 without. Cost: $0.10/mo
# in EBS reserved space, vs. ~$8/mo to bump to t3.small.
if [ ! -f /swapfile ]; then
    dd if=/dev/zero of=/swapfile bs=1M count=1024 status=none
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi

# Systemd unit so the app comes back automatically on reboot or AWS
# auto-recovery (we got bitten by this in May 2026: AWS replaced the
# instance, EBS volume reattached with repo + secrets intact, but Docker
# Engine started without any containers — `docker ps` was empty, site
# was 503 until a human ran `docker compose up`. This unit fixes that.)
#
# The deploy-phase-1.sh writes the repo + .env + secrets.toml, so first-
# boot has nothing to start (compose.aws.yml absent → unit exits cleanly).
# Subsequent reboots find the repo on the EBS volume and bring the stack
# back up.
cat > /etc/systemd/system/mindmarket.service <<'UNIT'
[Unit]
Description=MindMarket app stack (docker compose)
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
User=ec2-user
Group=docker
WorkingDirectory=/home/ec2-user/PersonalFinancialRiskManagement
# Idempotent. Silently no-op when the repo hasn't been deployed yet
# (first boot before deploy-phase-1.sh runs).
#
# AWS instance-recovery sometimes attaches a stale EBS snapshot, which
# would otherwise leave the EC2 running an older commit than what's on
# main. ExecStartPre does a `git pull --ff-only origin main` so a
# recovered instance self-heals to head before docker comes up.
# Best-effort — network failures are tolerated (`|| true`), and a
# divergent local branch would block fast-forward safely instead of
# clobbering local changes.
ExecStartPre=/bin/sh -c 'test -f compose.aws.yml || exit 0; cd /home/ec2-user/PersonalFinancialRiskManagement && /usr/bin/git fetch --quiet origin main || true; /usr/bin/git reset --quiet --hard origin/main || true'
ExecStart=/bin/sh -c 'test -f compose.aws.yml || exit 0; exec /usr/bin/docker compose -f compose.aws.yml up -d --build'
ExecStop=/bin/sh -c 'test -f compose.aws.yml || exit 0; exec /usr/bin/docker compose -f compose.aws.yml down'
TimeoutStartSec=15min

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable mindmarket.service

# Marker file. deploy-phase-1.sh polls for this to know bootstrap is done.
touch /var/lib/mindmarket-bootstrap-complete
echo "==> bootstrap finished $(date -u)"
"""


class ComputeStack(Stack):
    """EC2 t3.micro + Elastic IP + IAM role for the MindMarket app."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        foundation: FoundationStack,
        public_key_material: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── SSH key pair (CDK creates it from the public key on disk) ──
        # When `public_key_material` is set, CDK infers the key type from
        # the key string itself; passing `type` explicitly is a contradiction.
        keypair = ec2.KeyPair(
            self,
            "Key",
            key_pair_name="mindmarket-aws",
            public_key_material=public_key_material,
        )

        # ── IAM instance role ─────────────────────────────────────────
        role = iam.Role(
            self,
            "InstanceRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            description="MindMarket EC2: CloudWatch + SSM + scoped Secrets Manager read",
            managed_policies=[
                # CW agent writes metrics + logs
                iam.ManagedPolicy.from_aws_managed_policy_name("CloudWatchAgentServerPolicy"),
                # Session Manager: shell access without inbound 22
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore"),
            ],
        )
        # Phase 3 will populate this prefix with real secrets. Granting
        # read access now (least privilege: only mindmarket/* keys, only
        # this account, only this region) so we can swap in Secrets
        # Manager without a stack update.
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "secretsmanager:GetSecretValue",
                    "secretsmanager:DescribeSecret",
                ],
                resources=[
                    f"arn:aws:secretsmanager:{self.region}:{self.account}:secret:mindmarket/*"
                ],
            )
        )

        # ── EC2 instance ──────────────────────────────────────────────
        # x86_64 (not Graviton t4g): Phase 1 prioritizes "the existing
        # Docker image just runs"; ~10% cost savings from arm64 are a
        # Phase 4 cost-optimization story, not a Phase 1 risk.
        self.instance = ec2.Instance(
            self,
            "App",
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.BURSTABLE3,
                ec2.InstanceSize.MICRO,
            ),
            machine_image=ec2.MachineImage.latest_amazon_linux2023(
                cpu_type=ec2.AmazonLinuxCpuType.X86_64,
            ),
            vpc=foundation.vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            security_group=foundation.app_sg,
            key_pair=keypair,
            role=role,
            require_imdsv2=True,  # block SSRF-style metadata abuse
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/xvda",
                    volume=ec2.BlockDeviceVolume.ebs(
                        volume_size=8,
                        volume_type=ec2.EbsDeviceVolumeType.GP3,
                        encrypted=True,
                        delete_on_termination=True,
                    ),
                ),
            ],
            user_data=ec2.UserData.custom(USER_DATA_SH),
            user_data_causes_replacement=False,
        )

        # ── Elastic IP attached to the instance ───────────────────────
        # Why CfnEIP instead of L2: at the time of writing, CDK's L2
        # `ec2.CfnEIP` is the only way to get a stable IPv4 we can hand
        # to nip.io for HTTPS without a real domain.
        eip = ec2.CfnEIP(self, "AppEip", domain="vpc")
        ec2.CfnEIPAssociation(
            self,
            "AppEipAssoc",
            eip=eip.ref,
            instance_id=self.instance.instance_id,
        )

        # ── Outputs ───────────────────────────────────────────────────
        CfnOutput(
            self,
            "InstanceId",
            value=self.instance.instance_id,
            description="EC2 instance id (for SSM start-session)",
        )
        CfnOutput(
            self,
            "PublicIp",
            value=eip.ref,
            description="Elastic IP - SSH and browser target",
            export_name="MindMarket-PublicIp",
        )
        CfnOutput(
            self,
            "SshCommand",
            value=f"ssh -i ~/.ssh/mindmarket_aws ec2-user@{eip.ref}",
            description="One-liner to SSH in (after bootstrap completes)",
        )
        CfnOutput(
            self,
            "SsmCommand",
            value=(
                f"aws ssm start-session --target {self.instance.instance_id} "
                f"--profile mindmarket --region {self.region}"
            ),
            description="Fallback shell access via Session Manager (no SSH needed)",
        )
