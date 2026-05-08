#!/usr/bin/env bash
# infra/scripts/deploy-phase-1.sh
#
# One-shot Phase 1 deploy:
#   1. cdk deploy --all                 (Foundation + Compute)
#   2. wait for EC2 user-data to finish (poll bootstrap marker)
#   3. ssh in: clone repo, scp secrets.toml, set SITE_HOST=<eip>.nip.io,
#      docker compose up
#   4. print HTTPS URL
#
# Idempotent: re-run after code changes; cdk handles diffs, the ssh block
# does `git pull` + `compose up -d --build`.
#
# Usage:
#     ./infra/scripts/deploy-phase-1.sh
#
# Requirements:
#     - aws cli configured with profile `mindmarket`
#     - ~/.ssh/mindmarket_aws (private key)
#     - .streamlit/secrets.toml (NOT committed; SCPed to EC2 each deploy)
#
# Cost (24/7): ~$9.30/mo. Run `./destroy.sh` when not actively demoing.

set -euo pipefail

PROFILE="mindmarket"
REGION="us-east-1"
SSH_KEY="$HOME/.ssh/mindmarket_aws"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(dirname "$SCRIPT_DIR")"
REPO_DIR="$(dirname "$INFRA_DIR")"

# ── Pre-flight ──────────────────────────────────────────────
[[ -f "$SSH_KEY" ]] || { echo "Missing $SSH_KEY"; exit 1; }
[[ -f "$REPO_DIR/.streamlit/secrets.toml" ]] || {
    echo "Missing $REPO_DIR/.streamlit/secrets.toml"
    echo "Phase 3 will replace this with Secrets Manager fetch at boot."
    exit 1
}

OPERATOR_IP=$(curl -fsS -4 ifconfig.me)
echo "▶ operator_ip = $OPERATOR_IP"

cd "$INFRA_DIR"
# shellcheck source=/dev/null
[[ -d .venv ]] && source .venv/bin/activate
export JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1

# ── Step 1: cdk deploy --all ────────────────────────────────
echo "▶ cdk deploy --all (this is the expensive step)"
cdk deploy --all \
    --profile "$PROFILE" \
    --context operator_ip="$OPERATOR_IP" \
    --require-approval never \
    --outputs-file cdk.out/outputs.json

# ── Step 2: extract Elastic IP from stack outputs ──────────
EIP=$(jq -r '.["MindMarket-Compute"].PublicIp' cdk.out/outputs.json)
INSTANCE_ID=$(jq -r '.["MindMarket-Compute"].InstanceId' cdk.out/outputs.json)

# SITE_HOST: pass `DOMAIN=mindmarket.app ./deploy-phase-1.sh` to use a real
# domain. Otherwise fall back to nip.io which works without DNS config but
# gives an ugly URL. Caddy will request a Let's Encrypt cert for whichever
# host name we pass — for a real domain you MUST point its DNS at the EIP
# BEFORE this runs (or the ACME HTTP-01 challenge will fail).
if [[ -n "${DOMAIN:-}" ]]; then
    SITE_HOST="$DOMAIN"
    echo "▶ EIP=$EIP  instance=$INSTANCE_ID  site_host=$SITE_HOST  (real domain)"
    echo "   ⚠️  Verify DNS A-record for $SITE_HOST → $EIP is in place,"
    echo "       otherwise Let's Encrypt cert issuance will fail."
else
    SITE_HOST="${EIP//./-}.nip.io"
    echo "▶ EIP=$EIP  instance=$INSTANCE_ID  site_host=$SITE_HOST  (nip.io fallback)"
fi

# ── Step 3: wait for SSH availability + user-data marker ────
echo "▶ waiting for SSH + bootstrap to complete (up to 5 min)..."
for attempt in {1..30}; do
    if ssh -i "$SSH_KEY" \
           -o StrictHostKeyChecking=accept-new \
           -o ConnectTimeout=5 \
           -o BatchMode=yes \
           "ec2-user@$EIP" \
           "test -f /var/lib/mindmarket-bootstrap-complete" 2>/dev/null; then
        echo "  ✓ bootstrap complete (attempt $attempt)"
        break
    fi
    echo "  ($attempt/30) not ready, sleeping 10s..."
    sleep 10
    if [[ $attempt -eq 30 ]]; then
        echo "  ✗ bootstrap did not finish in 5 min."
        echo "    Inspect: ssh -i $SSH_KEY ec2-user@$EIP 'sudo cat /var/log/mindmarket-bootstrap.log'"
        echo "    Or:      aws ssm start-session --target $INSTANCE_ID --profile $PROFILE"
        exit 1
    fi
done

# ── Step 4: SCP secrets.toml + Caddyfile + compose.aws.yml ──
echo "▶ uploading config to EC2..."
scp -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new \
    "$REPO_DIR/.streamlit/secrets.toml" \
    "ec2-user@$EIP:/tmp/secrets.toml"

# ── Step 5: clone/pull repo + start docker compose ──────────
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new \
    "ec2-user@$EIP" \
    "SITE_HOST='$SITE_HOST' bash -s" <<'REMOTE'
set -euxo pipefail
cd ~

# Clone or fast-forward
if [[ ! -d PersonalFinancialRiskManagement ]]; then
    git clone https://github.com/zhengbrody/PersonalFinancialRiskManagement.git
fi
cd PersonalFinancialRiskManagement
git fetch origin
git checkout aws-migration
git reset --hard origin/aws-migration

# Place secrets.toml
mkdir -p .streamlit
mv /tmp/secrets.toml .streamlit/secrets.toml
chmod 600 .streamlit/secrets.toml

# Inject env vars docker compose reads from .env
cat > .env <<ENVFILE
SITE_HOST=${SITE_HOST}
ENVFILE

# Pull secrets into env vars too (compose.aws.yml expects them)
{
    grep -E '^(ANTHROPIC|DEEPSEEK|FMP)_API_KEY' .streamlit/secrets.toml \
        | sed 's/ *= */=/; s/"//g' || true
} >> .env

# Bring it up
docker compose -f compose.aws.yml up -d --build

# Wait for the app to report healthy (stream-line the deploy timeline)
for _ in {1..20}; do
    state=$(docker compose -f compose.aws.yml ps --format json app \
            | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('Health','none'))" 2>/dev/null \
            || echo none)
    if [[ "$state" == "healthy" ]]; then
        echo "  ✓ app healthy"
        break
    fi
    sleep 5
done
REMOTE

# ── Done ────────────────────────────────────────────────────
echo
echo "================================================================"
echo "  ✅ Deploy complete"
echo "================================================================"
echo "  HTTPS:  https://${SITE_HOST}"
echo "          (Caddy is fetching a Let's Encrypt cert; first hit may"
echo "           take 10-30s while ACME completes)"
echo
echo "  HTTP:   http://${EIP}        (redirects to HTTPS)"
echo
echo "  SSH:    ssh -i ${SSH_KEY} ec2-user@${EIP}"
echo "  SSM:    aws ssm start-session --target ${INSTANCE_ID} --profile ${PROFILE}"
echo
echo "  Logs:   https://${REGION}.console.aws.amazon.com/cloudwatch/home?region=${REGION}#logsV2:log-groups"
echo
echo "  💰 Tear down when idle:  ./infra/scripts/destroy.sh --force"
echo "================================================================"
