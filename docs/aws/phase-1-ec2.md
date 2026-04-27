# Phase 1 — EC2 Lift-and-Shift Runbook

> Single EC2 in `us-east-1`, public IP via Elastic IP, Caddy sidecar terminates
> Let's Encrypt TLS using `<eip>.nip.io`. Streamlit runs in Docker.
> Bootstrap by `cdk` user-data, app deploy by `deploy-phase-1.sh` over SSH.

## Architecture (current state)

```
Browser
  │ HTTPS (Let's Encrypt cert via nip.io)
  ▼
EIP (e.g. 18.215.123.45)
  │
  ├─► EC2 t3.micro (AL2023) in PublicSubnet1
  │      ├─ docker compose service `caddy` (ports 80, 443)
  │      │     └─ reverse_proxy ─► docker compose service `app` :8501
  │      │                                  └─ Streamlit ─► (FMP, Anthropic, yfinance)
  │      └─ CloudWatch Agent ─► /mindmarket/ec2/bootstrap log group
  │                              MindMarket/EC2 metrics namespace
  │
  └─ IAM role: CloudWatchAgentServerPolicy + AmazonSSMManagedInstanceCore
                + secretsmanager read on mindmarket/* (Phase 3 placeholder)
```

## Cost (24/7 if left running)

| Item | Monthly |
|---|---|
| EC2 t3.micro on-demand (no Free Tier under 2025 Free Plan) | ~$8.50 |
| EBS gp3 8 GB | ~$0.64 |
| EIP attached | $0 |
| EIP unattached (after destroy without releasing) | **$3.60** |
| Egress < 1 GB/mo | ~$0.09 |
| **Total** | **~$9.30** |

Strategy: deploy when demoing, `./infra/scripts/destroy.sh --force` when not.

## Deploy

```bash
./infra/scripts/deploy-phase-1.sh
```

What it does (in order):

1. `cdk deploy --all` — Foundation + Compute (90 s if first time, 30 s after)
2. Polls `/var/lib/mindmarket-bootstrap-complete` over SSH (~2 min after EC2 launch)
3. SCPs `.streamlit/secrets.toml` to EC2 `~/PersonalFinancialRiskManagement/.streamlit/`
4. SSH: `git clone` + `git checkout aws-migration` + `git pull`
5. SSH: writes `.env` with `SITE_HOST=<eip-dashes>.nip.io` and the API keys
6. SSH: `docker compose -f compose.aws.yml up -d --build`
7. Waits up to 100 s for the app healthcheck to flip green
8. Prints the HTTPS URL

Total wall time: 8–12 min on first deploy (Docker build dominates).
Subsequent deploys with `--build` cached: 2–4 min.

## Destroy

```bash
./infra/scripts/destroy.sh --force
```

Tears down ComputeStack first, then FoundationStack (cdk destroy walks the
DAG correctly). Verify in console:

- CloudFormation: stacks gone
- EC2 → Elastic IPs: **CRITICAL** — must show no unattached EIPs.
  An orphan EIP costs $3.60/mo even with the EC2 gone.

## Common issues

### 1. Can't SSH (timeout)

Most likely your residential IP changed (Comcast assigns dynamic IPs).

```bash
# Check what IP CDK currently allows:
aws ec2 describe-security-groups --profile mindmarket \
  --group-ids "$(aws ec2 describe-security-groups --profile mindmarket \
                  --filter Name=group-name,Values=*AppSg* \
                  --query 'SecurityGroups[0].GroupId' --output text)" \
  --query 'SecurityGroups[0].IpPermissions[?FromPort==`22`].IpRanges[].CidrIp'

# Compare to your current public IPv4:
curl -s -4 ifconfig.me

# If different, redeploy (FoundationStack picks up new operator_ip):
./infra/scripts/deploy-phase-1.sh
```

Fallback that doesn't depend on SG — Session Manager:

```bash
aws ssm start-session --target i-xxxxx --profile mindmarket --region us-east-1
```

### 2. Container won't start

```bash
ssh -i ~/.ssh/mindmarket_aws ec2-user@$EIP

cd ~/PersonalFinancialRiskManagement
docker compose -f compose.aws.yml ps
docker compose -f compose.aws.yml logs --tail=200 app
docker compose -f compose.aws.yml logs --tail=200 caddy
```

Or fetch from CloudWatch without SSHing:

```bash
aws logs tail /mindmarket/app   --profile mindmarket --since 10m --follow
aws logs tail /mindmarket/caddy --profile mindmarket --since 10m --follow
```

### 3. Port 8501 refused (after `compose up`)

Symptoms: container shows `Up`, but `curl http://localhost:8501` from inside
the EC2 fails.

Streamlit needs `--server.address=0.0.0.0` (default `localhost` only listens
inside the container). The Dockerfile already passes this correctly. If
someone overrode `command:` in compose, restore it.

```bash
docker compose -f compose.aws.yml exec app curl -fsS http://localhost:8501/_stcore/health
```

### 4. Caddy serves a self-signed cert (browser warning)

Means Let's Encrypt issuance failed (nip.io DNS not resolving the EIP, or :80
not reachable, or rate limit hit). Check Caddy logs:

```bash
aws logs tail /mindmarket/caddy --profile mindmarket --since 30m \
    | grep -iE "error|tls|acme"
```

Common fixes:
- Confirm SG allows 80/tcp from 0.0.0.0/0 (FoundationStack does this).
- Confirm `SITE_HOST` env var is set: `docker compose exec caddy env | grep SITE_HOST`.
- Hit the Let's Encrypt rate limit? (5 cert issuances per domain per week.)
  Wait, or use the staging endpoint by adding `acme_ca https://acme-staging-v02.api.letsencrypt.org/directory`
  to the Caddyfile.

### 5. Out of memory

`t3.micro` has 1 GB RAM. The Streamlit image (numpy/scipy/pandas/yfinance)
sits at ~500 MB resident, plus Caddy ~50 MB, plus AL2023 baseline ~250 MB.
Margin is thin.

Symptoms: `docker ps` shows app exited 137 (OOM kill).

```bash
free -m
docker stats --no-stream
```

Quick fixes:
- Add 1 GB swap (free, takes 30 sec):
  ```bash
  sudo dd if=/dev/zero of=/swapfile bs=1M count=1024
  sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
  ```
- Or upsize to t3.small (~$17/mo) — change CDK `InstanceSize.MICRO` to `SMALL`,
  redeploy.

Permanent fix lives in Phase 2 (move heavy compute to Lambda; Streamlit just
renders).

### 6. `cdk deploy` fails with "current credentials could not be used to assume role"

Bootstrap was missing or wrong account. Verify:

```bash
aws sts get-caller-identity --profile mindmarket  # → 520622116862
aws cloudformation describe-stacks --profile mindmarket --stack-name CDKToolkit \
    --query 'Stacks[0].StackStatus'                # → CREATE_COMPLETE
```

If CDKToolkit missing:

```bash
cd infra && source .venv/bin/activate
cdk bootstrap aws://520622116862/us-east-1 \
    --profile mindmarket --context operator_ip="$(curl -s -4 ifconfig.me)"
```

## Verification after deploy

```bash
# Stack outputs
aws cloudformation describe-stacks --profile mindmarket \
    --stack-name MindMarket-Compute \
    --query 'Stacks[0].Outputs[*].[OutputKey,OutputValue]' --output table

# App health from inside the EC2
ssh -i ~/.ssh/mindmarket_aws ec2-user@$EIP \
    "curl -fsS http://localhost:8501/_stcore/health"

# CloudWatch metrics arriving
aws cloudwatch list-metrics --profile mindmarket \
    --namespace MindMarket/EC2 --output table

# Browser
open https://${EIP//./-}.nip.io
```
