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
- Wrote `ComputeStack`: t3.micro AL2023 in PublicSubnet1, EIP, IMDSv2 required, 8GB gp3 encrypted, IAM with CWAgentServer + SSMManagedInstanceCore + scoped Secrets Manager read on `mindmarket/*`. User-data installs docker + compose v2 + CloudWatch Agent and writes a bootstrap-complete marker. SSH key imported from `~/.ssh/mindmarket_aws.pub`. Synth ✅ (9 resources).
- Hit two CDK API gotchas: (a) `KeyPair(type=ED25519)` rejected when `public_key_material` is set — type is inferred from the key string, (b) factory method is `latest_amazon_linux2023` not `..._2023`.
- Wrote `compose.aws.yml` (production-ish, separate from local `docker-compose.yml`): Caddy sidecar, awslogs driver shipping app + caddy stdout to CloudWatch, healthchecks, app no longer publishes :8501 to host (only Caddy reaches it via docker network).
- Wrote `Caddyfile`: `{$SITE_HOST}` block with WebSocket-friendly read/write timeouts; `:80` fallback responds 503 during bootstrap.
- Wrote `infra/scripts/deploy-phase-1.sh`: cdk deploy + poll bootstrap marker + scp secrets.toml + git checkout + compose up + healthcheck wait + print URL. Idempotent (rerun after code changes).
- Wrote `docs/aws/phase-1-ec2.md` runbook: arch diagram, cost, deploy/destroy flows, top 6 common issues with copy-paste debugging commands.
- **Phase 1 milestone hit**: end-to-end deploy via `./infra/scripts/deploy-phase-1.sh` succeeded. EC2 launched, user-data installed Docker + buildx 0.18 + Compose v2 + CloudWatch agent, repo cloned, app + Caddy compose stack came up, Caddy obtained Let's Encrypt cert via HTTP-01 challenge. Public HTTPS URL `https://75-101-197-112.nip.io` returned HTTP/2 200; cert issuer `Let's Encrypt E7`, valid 90 days; `_stcore/health` returned `ok` through the full chain.
- Two real bugs found-and-fixed during deploy (committed in `a265d44`):
  1. `compose build requires buildx 0.17.0 or later` — AL2023's bundled buildx is 0.12, pinned v0.18.0 in user-data.
  2. healthcheck used `curl` but `python:3.10-slim` doesn't include it; switched to `python -c 'import urllib.request; ...'`.
- Drafted `docs/adr/0002-phase2-compute-design.md` (research done in parallel via subagent during deploy wait): Container Image Lambda > Zip+Layers (numpy/scipy/pandas blow 250 MB cap), single-table DynamoDB w/ `TICKER#sym` + `BAR#granularity#ts`, HTTP API + Lambda authorizer beats REST API, scheduled-warmer + Python SnapStart for cold starts. Phase 2 cost ~$8/mo.
- **Destroy verified**: ComputeStack + FoundationStack gone in 3 min, no residue. CDKToolkit retained (~$0.02/mo standing). Unattached EIPs: 0 (the $3.60/mo trap was avoided).
- Total Phase 1 spend: well under $1 (deploy + 30 min running + destroy across 2 deploys today). $99+ of $100 credits remain.
- **Phase 2 code complete** — entered post-Phase-1 sprint with full architectural autonomy delegated by user.
- Decision flipped HTTP API → **REST API** for Phase 2 (ADR-0002 finalized, status Accepted): native usage_plan + api_key beats $0.13/mo savings + custom Lambda authorizer.
- Extracted `libs/mindmarket_core/` (5 modules, ~600 LOC, all pure compute, zero I/O): `constants`, `var`, `portfolio_math`, `black_scholes`, `data_prep`. Zero behavioral changes — existing risk_engine.py / options_engine.py / data_provider.py public API preserved verbatim.
- 46 new unit tests against textbook references: BS price S=K=100 r=5% σ=20% T=1 → $10.4506 (Hull eq. 17.5), put-call parity holds 1e-6, IV roundtrip 1e-5 across [0.1, 0.6], VaR/CVaR sign+ordering invariants, drawdown episode counting, compliance tolerance 1e-6 no false positives.
- Wrote 3 Lambda handlers: risk-calculator (POST /var, 3GB memory), options-pricer (POST /greeks, 512MB), price-cache (GET /price/{ticker}, 1GB, only DDB writer). All pass 19 local mock tests.
- Wrote `Dockerfile` × 3 — `public.ecr.aws/lambda/python:3.11` base, build context = repo root so `COPY libs/` works. Added `**/cdk.out/`, `**/__pycache__/` to `.dockerignore` after CDK first-run blew up with ENAMETOOLONG (recursive copy).
- Wrote `DataStack` (DynamoDB PriceCache, on-demand, TTL=expiresAt, no GSI per ADR-0002) and `ApiStack` (REST API + 3 DockerImageFunctions + UsagePlan 1000/day + ApiKey, least-privilege IAM: only price-cache can DDB-write, all 3 can DDB-read). Both stacks `cdk synth` clean.
- Wrote `libs/remote_compute.py` (thin REST API client) + 14 tests, plus pages/2_Risk.py expander for side-by-side local-vs-Lambda VaR comparison gated on `USE_REMOTE_COMPUTE=1`.
- Wrote `.github/workflows/deploy-services.yml` — matrix-tests each service, gates AWS deploy behind OIDC role + manual enable.
- Tests: 656 pass (596 baseline + 46 libs + 14 remote_compute), services tests run separately (3 services × 7+7+5 = 19, namespace-isolated).
- Pre-deploy state: nothing deployed in AWS yet. Phase 1 stacks already destroyed; only CDKToolkit standing (~$0.02/mo). Phase 2 deploy is task #9, gated on user confirmation since EC2-free Lambda+DDB+API GW deploy still costs ~$3-5/mo while running.
- **Phase 2 milestone hit** — full deploy + smoke + destroy roundtrip. 3 real bugs surfaced during deploy:
  1. **Cross-arch image (1st deploy fail)**: M-series Mac builds arm64 docker images by default but Lambda is x86_64. risk + options pushed silently as arm64 (would crash on first invoke); price-cache failed at `pip install` because numpy lacked an arm64 wheel and the Lambda base has no compiler. **Fix:** `platform=ecr_assets.Platform.LINUX_AMD64` on every `DockerImageCode.from_image_asset`.
  2. **Eager `__init__.py` (2nd deploy fail)**: ApiStack deployed clean, but `/greeks` returned HTTP 502 with `Runtime.ImportModuleError: No module named 'pandas'`. Root cause: `libs/mindmarket_core/__init__.py` did `from . import var` and `var.py` imports pandas; options-pricer service deliberately omits pandas. **Fix:** empty `__init__.py`; consumers do `from libs.mindmarket_core import black_scholes` directly so only the needed submodule loads.
  3. **yfinance 0.2.50 vs Yahoo API drift**: `/price/AAPL` returned `JSONDecodeError: Expecting value: line 1 column 1`. Same on MSFT/TSLA/SPY. yfinance pinned 6 months ago, Yahoo's HTML/API contract has shifted. **Triage:** architecture is sound (Lambda → DDB → external fetch chain works; error response shape correct). Mitigation deferred to Phase 4 cost-optimization sweep where we re-evaluate FMP/Polygon as primary feed.
- Smoke test results (3rd deploy):
  - `/greeks` ATM 1Y call S=K=100 r=5% σ=20% → **price 10.4506, delta 0.6368** (matches Hull 17.5 exactly), 156 ms warm
  - `/var` 3-asset synthetic returns → **VaR 95% 6.12%, CVaR 95% 7.17%** (CVaR ≥ VaR ✓), 9 s cold (scipy+pandas import dominates), <1 s warm
  - `/price/*` chain works architecturally; data source broken upstream
- **Destroy verified clean** — 0 stacks except CDKToolkit, 0 Lambdas, 0 DDB tables, 0 unattached EIPs.
- Total Phase 2 deploy spend: <$0.20 (3 docker pushes to ECR, ~30 minutes total Lambda/API/DDB running across 3 deploys, then teardown).
