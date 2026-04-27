#!/usr/bin/env python3
"""
MindMarket AI — CDK app entry point.

Phase 1 stacks:
    - MindMarket-Foundation : VPC + SG + S3 logs

Run with explicit profile so we never accidentally deploy from the wrong
identity:

    cdk synth   --profile mindmarket --context operator_ip=$(curl -s -4 ifconfig.me)
    cdk diff    --profile mindmarket --context operator_ip=$(curl -s -4 ifconfig.me)
    cdk deploy  --profile mindmarket --context operator_ip=$(curl -s -4 ifconfig.me) --all

`operator_ip` is the public IPv4 you SSH from. It's checked into CDK
context (NOT committed) and pinned into the SG ingress rule.
"""
from __future__ import annotations

import os
import sys

import aws_cdk as cdk

from infra.foundation_stack import FoundationStack

# Hard-pin account + region. CDK supports env-agnostic stacks but we lose
# context lookups (VPC AZs, AMI IDs) — and silent cross-account surprise
# deploys are exactly the kind of mistake `aws-vault` users hit.
ACCOUNT = "520622116862"
REGION = "us-east-1"
env = cdk.Environment(account=ACCOUNT, region=REGION)


def _resolve_operator_ip(app: cdk.App) -> str:
    """Read operator_ip from --context flag or OPERATOR_IP env. Required."""
    ip = os.environ.get("OPERATOR_IP") or app.node.try_get_context("operator_ip")
    if not ip:
        sys.stderr.write(
            "\nERROR: missing operator_ip. Provide via either:\n"
            "  --context operator_ip=$(curl -s -4 ifconfig.me)\n"
            "  OPERATOR_IP=$(curl -s -4 ifconfig.me) cdk ...\n\n"
        )
        sys.exit(2)
    return ip


app = cdk.App()
operator_ip = _resolve_operator_ip(app)

FoundationStack(
    app,
    "MindMarket-Foundation",
    operator_ip=operator_ip,
    env=env,
    description="MindMarket AI — VPC, security group, S3 logs (Phase 1).",
)

app.synth()
