#!/usr/bin/env python3
"""
MindMarket AI -- CDK app entry point.

Stacks (deploy order driven by CDK dependency graph):
    Phase 1:
        - MindMarket-Foundation : VPC + SG + S3 logs (~$0/mo)
        - MindMarket-Compute    : EC2 + EIP + IAM    (~$9.30/mo when running)
    Phase 2:
        - MindMarket-Data       : DynamoDB PriceCache (free at our scale)
        - MindMarket-Api        : REST API + 3 Lambdas + usage plan (~$3-5/mo active)

Run with explicit profile so we never accidentally deploy from the wrong
identity:

    cdk synth   --profile mindmarket --context operator_ip=$(curl -s -4 ifconfig.me)
    cdk diff    --profile mindmarket --context operator_ip=$(curl -s -4 ifconfig.me)
    cdk deploy  --profile mindmarket --context operator_ip=$(curl -s -4 ifconfig.me) --all

Inputs:
    operator_ip          : your public IPv4 (CDK context or OPERATOR_IP env)
    ssh_pubkey_path      : path to the SSH pubkey to upload as EC2 KeyPair
                           (defaults to ~/.ssh/mindmarket_aws.pub)
"""
from __future__ import annotations

import os
import pathlib
import sys

import aws_cdk as cdk

from infra.api_stack import ApiStack
from infra.compute_stack import ComputeStack
from infra.data_stack import DataStack
from infra.foundation_stack import FoundationStack

ACCOUNT = "520622116862"
REGION = "us-east-1"
env = cdk.Environment(account=ACCOUNT, region=REGION)


def _resolve_operator_ip(app: cdk.App) -> str:
    ip = os.environ.get("OPERATOR_IP") or app.node.try_get_context("operator_ip")
    if not ip:
        sys.stderr.write(
            "\nERROR: missing operator_ip. Provide via either:\n"
            "  --context operator_ip=$(curl -s -4 ifconfig.me)\n"
            "  OPERATOR_IP=$(curl -s -4 ifconfig.me) cdk ...\n\n"
        )
        sys.exit(2)
    return ip


def _resolve_ssh_pubkey(app: cdk.App) -> str:
    """Load the public key contents from disk; fail loudly if missing."""
    path_str = (
        os.environ.get("SSH_PUBKEY_PATH")
        or app.node.try_get_context("ssh_pubkey_path")
        or "~/.ssh/mindmarket_aws.pub"
    )
    path = pathlib.Path(path_str).expanduser()
    if not path.exists():
        sys.stderr.write(
            f"\nERROR: SSH public key not found at {path}.\n"
            "Generate one with:\n"
            "  ssh-keygen -t ed25519 -f ~/.ssh/mindmarket_aws -N '' -C 'mindmarket-aws'\n\n"
        )
        sys.exit(2)
    return path.read_text().strip()


app = cdk.App()
operator_ip = _resolve_operator_ip(app)
ssh_pubkey = _resolve_ssh_pubkey(app)

foundation = FoundationStack(
    app,
    "MindMarket-Foundation",
    operator_ip=operator_ip,
    env=env,
    description="MindMarket AI VPC, security group, S3 logs (Phase 1).",
)

ComputeStack(
    app,
    "MindMarket-Compute",
    foundation=foundation,
    public_key_material=ssh_pubkey,
    env=env,
    description="MindMarket AI EC2 instance running Streamlit (Phase 1).",
)

# Phase 2 — independent of Foundation/Compute, can deploy without EC2 running.
data = DataStack(
    app,
    "MindMarket-Data",
    env=env,
    description="MindMarket DynamoDB tables (Phase 2).",
)

ApiStack(
    app,
    "MindMarket-Api",
    price_cache_table=data.price_cache,
    env=env,
    description="MindMarket REST API + Lambdas + usage plan (Phase 2).",
)

app.synth()
