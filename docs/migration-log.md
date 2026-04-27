# MindMarket AI — AWS Migration Log

> One-line dated entries. Raw material for blog posts and STAR stories.
> Append, don't edit. Format: `YYYY-MM-DD — what happened`.

---

## 2026-04-26
- Scoped 4-phase AWS migration plan (lift-and-shift → Lambda extract → async + auth + observability → polish + interview prep).
- Confirmed AWS account on **new Free Plan** model: $100 credits, 185 days, no legacy 12-month free tier; all spend draws from credits.
- Set monthly budget alarm at $20 (target $16/mo, ceiling $20/mo, total ~$110 over 6 months).
- Rotated Anthropic + DeepSeek API keys; FMP deferred (audit confirmed never committed to git history).
- Created IAM `mindmarket-deploy` user with `AdministratorAccess` (will narrow in Phase 3).
- Installed local toolchain: AWS CLI v2.34, CDK v2.1119, Docker v29.3, Node v25, Python 3.12.
- `aws sts get-caller-identity --profile mindmarket` returned account `520622116862` ✅.
- Bootstrapped CDK Python project at `infra/` on new branch `aws-migration`.
- Hard-pinned CDK env to account + region (no env-agnostic surprise deploys).
- Wrote `infra/scripts/destroy.sh` stub before any deploy script — destroy-first habit.
- Smoke-tested existing `docker-compose up` on Mac: 2.01 GB image, Streamlit serves :8501, HTTP 200. Dockerfile is fresh-environment safe — no surprises waiting for us on EC2.
- Removed obsolete `version: '3.8'` from `docker-compose.yml` (Compose v2 ignores it).
- Wrote `FoundationStack`: 2-AZ VPC at 10.0.0.0/16, public + private isolated subnets, **0 NAT gateways** (saves $32-64/mo), SG (443+80 world / 22 operator-only), CloudFront logs S3 bucket pre-provisioned (empty, 30-day lifecycle).
- Wrote `docs/adr/0001-foundation-vpc-design.md` — full rationale + alternatives + anticipated changes.
- `cdk synth` produces 27 resources, 3 outputs. SG ingress rules verified against spec.
- **First-ever AWS deploy**: bootstrapped CDK in `aws://520622116862/us-east-1` (CDKToolkit, ~$0.02/mo standing). First FoundationStack deploy failed: SG description had em-dash `—` (EC2 SG descriptions are ASCII-only). CloudFormation auto-rolled back cleanly — zero residual resources. **Lesson: SG/IAM description fields go straight to AWS APIs that may not be UTF-8 tolerant.**
- Replaced em-dashes with ASCII; redeployed in 61 s. Verified: SG has 3 ingress rules matching spec, S3 bucket has AES256 + 30-day lifecycle, 4 subnets across 2 AZs.
- **Destroy roundtrip verified**: `./infra/scripts/destroy.sh --force` removed everything cleanly (2 min). VPC gone, stack ValidationError on describe. Re-deploy gave new VPC ID `vpc-07b51749fe5ae60ea` ≠ previous `vpc-0ea6bc91d990bced3` — confirms idempotent reconstruction, not a recovered resource.
- Cost so far: ~$0 (CDKToolkit standing only, FoundationStack itself is free until ComputeStack adds EC2).
