#!/usr/bin/env python3
"""
MindMarket AI — CDK app entry point.

Phase 1: defines FoundationStack (VPC + SG + S3 logs)
                  ComputeStack    (EC2 + EIP + IAM role)

Run with explicit profile so we never accidentally deploy from the wrong
identity:

    cdk synth   --profile mindmarket
    cdk diff    --profile mindmarket
    cdk deploy  --profile mindmarket --all

Environment is read from `cdk.context.json` (committed) + `--context` flags
(per-deploy overrides). See `cdk.json` for defaults.
"""
from __future__ import annotations

import os

import aws_cdk as cdk

# Hard-pin account + region. CDK supports env-agnostic stacks but we lose
# context lookups (VPC AZs, AMI IDs) — and silent cross-account surprise
# deploys are exactly the kind of mistake `aws-vault` users hit.
ACCOUNT = "520622116862"
REGION = "us-east-1"

env = cdk.Environment(account=ACCOUNT, region=REGION)

app = cdk.App()

# Stacks will be added here as Phase 1 progresses.
# from infra.foundation_stack import FoundationStack
# from infra.compute_stack import ComputeStack
# foundation = FoundationStack(app, "MindMarket-Foundation", env=env)
# ComputeStack(app, "MindMarket-Compute", foundation=foundation, env=env)

app.synth()
