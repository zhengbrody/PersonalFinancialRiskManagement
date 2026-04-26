#!/usr/bin/env bash
# infra/scripts/destroy.sh
#
# Tear down EVERY MindMarket AWS stack. Run this before ending a work
# session so we don't burn Free Plan credits overnight.
#
# Order matters: stacks with dependents must come down BEFORE the stacks
# they depend on (CloudFormation enforces this with errors otherwise).
#
#   ComputeStack    →  uses VPC + SG from FoundationStack
#   FoundationStack →  no deps
#
# Usage:
#     ./infra/scripts/destroy.sh           # interactive, asks before each
#     ./infra/scripts/destroy.sh --force   # skip prompts (CI / scripted)
#
# Exit codes:
#     0 — all stacks destroyed (or none existed)
#     1 — destroy command failed; resources may still exist (re-run, or
#         inspect via CloudFormation console)
set -euo pipefail

PROFILE="mindmarket"
REGION="us-east-1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(dirname "$SCRIPT_DIR")"

cd "$INFRA_DIR"

# Use the venv's cdk Python deps but the global cdk CLI.
# shellcheck source=/dev/null
[[ -d .venv ]] && source .venv/bin/activate

export JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1

FORCE_FLAG=""
if [[ "${1:-}" == "--force" ]]; then
    FORCE_FLAG="--force"
fi

echo "▶ Listing CDK stacks..."
STACKS=$(cdk ls --profile "$PROFILE" 2>/dev/null || true)

if [[ -z "$STACKS" ]]; then
    echo "  (no stacks defined locally — nothing to destroy)"
    exit 0
fi

echo "Stacks: $STACKS"
echo
echo "▶ Destroying in dependency-safe order..."

# `cdk destroy --all` walks the DAG correctly. We pass `--profile` so we
# never tear down resources in another account by accident.
cdk destroy --all \
    --profile "$PROFILE" \
    $FORCE_FLAG

echo
echo "✅ destroy complete. Verify in Console:"
echo "   https://${REGION}.console.aws.amazon.com/cloudformation/home?region=${REGION}#/stacks"
echo
echo "💰 Reminder: also check for orphaned resources NOT created by CDK:"
echo "   - EBS volumes (Console → EC2 → Volumes)"
echo "   - Elastic IPs (Console → EC2 → Elastic IPs — \$3.60/mo if unattached!)"
echo "   - S3 buckets with retain policy (Console → S3)"
