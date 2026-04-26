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
