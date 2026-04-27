"""
infra/foundation_stack.py

Network + base infrastructure that other stacks reference. Owns long-lived,
rarely-changing primitives — VPC, security groups, the CloudFront-logs S3
bucket. Compute lives elsewhere (ComputeStack) so iterating on EC2
user-data doesn't risk the VPC.

Decisions worth knowing (full rationale in docs/adr/0001-foundation-vpc-design.md):

  - **2 AZs, not 3.** CDK default is 3; we override `max_azs=2`. AZs
    themselves are free, but cross-AZ data transfer ($0.01/GB) and
    "one NAT gateway per AZ" ($32/mo each) bite at scale. Phase 1
    only ever runs one EC2 anyway.

  - **Zero NAT gateways.** Outbound from private subnets normally
    requires NAT ($32/mo per AZ). Free Plan budget is $33/mo TOTAL.
    We use PRIVATE_ISOLATED subnets (no internet egress) for the
    private tier. Phase 2 Lambdas live OUTSIDE the VPC by default;
    if we later move them inside, we'll add free VPC endpoints
    (S3 gateway, DynamoDB gateway, interface endpoints for SSM /
    Secrets Manager) — never NAT.

  - **Port 80 + 443 ingress, but only 22 from operator IP.** Caddy
    in the EC2 sidecar needs port 80 reachable for Let's Encrypt's
    HTTP-01 ACME challenge. Once we have a real domain (Phase 4)
    we can switch to DNS-01 challenge and close port 80.

  - **S3 logs bucket has destroy=DESTROY + auto_delete=True.** Tear-
    down friendliness for Phase 1. In a production stack we'd RETAIN
    and use bucket versioning + an Object Lock retention period.
"""

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_ec2 as ec2,
    aws_s3 as s3,
)
from constructs import Construct


class FoundationStack(Stack):
    """VPC, security group, and S3 bucket for CloudFront logs."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        operator_ip: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self._validate_operator_ip(operator_ip)

        # ── VPC ───────────────────────────────────────────────────
        # 10.0.0.0/16 → /24 subnets gives 256 hosts/subnet. Plenty
        # for a single EC2 + future ECS tasks.
        self.vpc = ec2.Vpc(
            self,
            "Vpc",
            ip_addresses=ec2.IpAddresses.cidr("10.0.0.0/16"),
            max_azs=2,
            nat_gateways=0,  # explicit; default would be 1 per AZ
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    cidr_mask=24,
                ),
            ],
        )

        # ── Security group for the app EC2 ────────────────────────
        self.app_sg = ec2.SecurityGroup(
            self,
            "AppSg",
            vpc=self.vpc,
            description="MindMarket app — public 80/443, ssh from operator only",
            allow_all_outbound=True,
        )
        self.app_sg.add_ingress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.tcp(443),
            description="HTTPS public",
        )
        self.app_sg.add_ingress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.tcp(80),
            description="HTTP — Caddy ACME HTTP-01 challenge",
        )
        self.app_sg.add_ingress_rule(
            peer=ec2.Peer.ipv4(f"{operator_ip}/32"),
            connection=ec2.Port.tcp(22),
            description=f"SSH from operator ({operator_ip})",
        )

        # ── S3 bucket for CloudFront logs ─────────────────────────
        # Pre-provision now so Phase 4's CloudFront enablement
        # doesn't trigger a stack refactor. Empty bucket = $0.
        self.logs_bucket = s3.Bucket(
            self,
            "CloudFrontLogs",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            # CloudFront standard logging requires ACL writes from the
            # service principal — OBJECT_WRITER allows it. Switching
            # to CloudFront *real-time* logs (Kinesis Firehose) in
            # Phase 3 lets us flip this back to BUCKET_OWNER_ENFORCED.
            object_ownership=s3.ObjectOwnership.OBJECT_WRITER,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="expire-30d",
                    enabled=True,
                    expiration=Duration.days(30),
                    abort_incomplete_multipart_upload_after=Duration.days(1),
                ),
            ],
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # ── Outputs (cross-stack refs surface here) ───────────────
        CfnOutput(
            self,
            "VpcId",
            value=self.vpc.vpc_id,
            export_name="MindMarket-VpcId",
        )
        CfnOutput(
            self,
            "AppSgId",
            value=self.app_sg.security_group_id,
            export_name="MindMarket-AppSgId",
        )
        CfnOutput(
            self,
            "LogsBucketName",
            value=self.logs_bucket.bucket_name,
            export_name="MindMarket-LogsBucket",
        )

    @staticmethod
    def _validate_operator_ip(ip: str) -> None:
        """Reject bad IPs early — better than a CloudFormation diff failure."""
        import ipaddress

        try:
            addr = ipaddress.ip_address(ip)
        except ValueError as e:
            raise ValueError(f"operator_ip {ip!r} is not a valid IP address") from e
        if isinstance(addr, ipaddress.IPv6Address):
            raise ValueError(
                f"operator_ip must be IPv4 (got IPv6 {ip}). "
                "Use `curl -s -4 ifconfig.me` to get your IPv4."
            )
        if addr.is_private or addr.is_loopback:
            raise ValueError(
                f"operator_ip {ip} is private/loopback — won't reach EC2 from internet."
            )
