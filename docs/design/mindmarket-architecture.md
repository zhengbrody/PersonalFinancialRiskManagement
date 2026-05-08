# MindMarket AI — Architecture & Engineering Design Doc

**Author:** Zheng Dong (`@zhengbrody`)
**Status:** v1 — covers Phase 0 (Streamlit monolith) → Phase 2 (Lambda extract) and the Phase 1 EC2 lift, deployed and verified live
**Format:** Amazon-style 6-pager. Read top-to-bottom; FAQ at the end answers everything not in the body.
**Live:** https://mindmarket.app (deployed on demand; idle when not demoing)
**Repo:** https://github.com/zhengbrody/PersonalFinancialRiskManagement (`aws-migration` branch)

---

## 1. Introduction

MindMarket AI is a portfolio risk-analytics platform with the analytical
depth of an institutional risk system (Monte Carlo VaR, multi-factor
attribution, options Greeks, regime detection, SEC 13F overlay) packaged as
a 10-page Streamlit dashboard accessible to a retail investor. This document
describes the system as it stands after a 4-week migration from a single-
process Streamlit Cloud deployment to a distributed AWS architecture
(VPC + EC2 + REST API Gateway + 3 containerized Lambdas + DynamoDB cache
+ Supabase Auth for per-user portfolios).

The goal of the document is to make the architecture, the trade-offs taken,
and the mistakes corrected legible to a new engineer joining the project —
or to a hiring manager trying to assess depth.

## 2. Tenets

These guided every design choice. Tied to Amazon Leadership Principles
where the mapping is direct.

1. **Destroy-first IaC.** Every `cdk deploy` is paired with one-command
   teardown, verified to leave zero orphan resources. No deploy lands
   without proving the destroy works first. *(Insist on High Standards)*

2. **Frugality before completeness.** A single `t3.micro` and on-demand
   DynamoDB beat over-provisioned HA when the user count is one.
   `destroy.sh` runs nightly when not demoing. Total Phase 1+2 spend
   verified at $0.70 of a $200 free-tier budget. *(Frugality)*

3. **Pure compute as a library, I/O at the edges.** `libs/mindmarket_core/`
   contains zero network calls, zero Streamlit imports, lazy package init.
   This makes the same numpy/scipy code reusable from Streamlit on EC2
   (Phase 1) and from Lambda (Phase 2) without edits. *(Invent and Simplify)*

4. **Match scope to evidence.** SnapStart, Provisioned Concurrency,
   Cognito, GSI on PriceCache — all left out of Phase 2 because the
   product doesn't have the user count to justify them yet. Each is a
   one-paragraph entry in the "Anticipated changes" section of the
   relevant ADR; none are implemented speculatively. *(Are Right, A Lot)*

5. **Real bugs, not gold stars.** Six bugs were found *during real
   deploys*, not in code review. Each is logged in the README's "What I
   Learned" table with the symptom, root cause, and lesson. The ones I
   could prevent in code (em-dash in CFN strings, eager package imports
   forcing cross-service deps) are now committed as guard tests; the
   ones I can't (yfinance vs Yahoo API drift) are flagged for Phase 4
   data-source replacement. *(Dive Deep)*

## 3. State of the business

Phase 1+2 milestones, all hit and verified live:

| Stack | Status | Verification |
|---|---|---|
| FoundationStack (VPC, SG, S3 logs) | Deployed and torn down 3× | `aws ec2 describe-vpcs` matches expected CIDR; SG ingress rules cross-checked against ADR-0001 |
| ComputeStack (EC2 + EIP + Caddy + CloudWatch agent) | Deployed and torn down 3× | `https://<eip>.nip.io` returned HTTP/2 200, Let's Encrypt cert from issuer "E7"; CloudWatch metrics arrive at `MindMarket/EC2` namespace |
| DataStack (DynamoDB on-demand) | Deployed and torn down 1× | RLS-equivalent isolation: anon GET on /portfolios returns `[]` |
| ApiStack (REST API + 3 Lambdas + UsagePlan + ApiKey) | Deployed and torn down 1× | `POST /greeks` returned price 10.4506 — matches Hull eq. 17.5 to 4 dp; warm latency 156 ms |
| Supabase Auth + per-user portfolios | Deployed live | Real account created (`a13105129007@gmail.com`), email confirmation round-trip verified, RLS policies enforced from anon JWT |
| Streamlit landing + dedup + active_portfolio resolver | Live | Headless playwright screenshot proves landing renders; 653 unit tests pass |

Spend so far (verified via `aws ce get-cost-and-usage`):

| Item | Spend |
|---|---|
| 3× Phase 1 deploy/destroy | < $0.50 |
| 3× Phase 2 deploy/destroy | < $0.20 |
| CDKToolkit (always-on bootstrap stack) | $0.02/mo |
| **Total** | **~$0.72** |

## 4. Architecture

### 4.1 Layered view

```
                            ┌─────────────────────────┐
                            │  CloudFront + WAF       │  Phase 4 (planned)
                            └────────────┬────────────┘
                                         │
                  ┌──────────────────────┴──────────────────────┐
                  │                                              │
          ┌───────▼────────┐                            ┌───────▼────────┐
          │  Streamlit UI  │  Phase 1                   │  REST API GW   │  Phase 2
          │  (EC2 t3.micro)│  ~$9.30/mo                 │  api_key,      │
          │  Caddy 443+80  │  Caddy auto-HTTPS via      │  1k req/day    │
          │  TLS Let's     │  Let's Encrypt HTTP-01     │  cap           │
          │  Encrypt       │  on mindmarket.app         └───────┬────────┘
          └───────┬────────┘                                    │
                  │ feature flag USE_REMOTE_COMPUTE              │
                  └─────────────────┐                            │
                                    │                            │
                         ┌──────────▼────────┐         ┌────────▼────────┐
                         │ Supabase Postgres │         │  3 × Lambda     │
                         │ + Auth + RLS      │         │  Container Img  │
                         │ (managed, free    │         │  numpy + scipy  │
                         │  tier)            │         │  + pandas       │
                         └──────────┬────────┘         └────────┬────────┘
                                    │                           │
                              ┌─────┴────────────────────────┐  │
                              │ portfolios(user_id, holdings)│  │
                              │ (RLS isolates per user)      │  │
                              └──────────────────────────────┘  │
                                                                │
                                                  ┌─────────────▼──────┐
                                                  │  DynamoDB          │
                                                  │  PriceCache        │
                                                  │  pk=TICKER#sym     │
                                                  │  sk=BAR#interval#  │
                                                  │  TTL=expiresAt     │
                                                  └────────────────────┘
```

### 4.2 Stack boundaries (CDK)

Four stacks, deliberately separate so iteration on one doesn't risk another:

- **MindMarket-Foundation** — VPC, security group, S3 logs bucket. ~$0/mo
  (no NAT, no KMS CMK).
- **MindMarket-Compute** — EC2 + EIP + IAM. References Foundation via
  cross-stack export. ~$9.30/mo when running.
- **MindMarket-Data** — DynamoDB PriceCache. On-demand, free tier.
- **MindMarket-Api** — REST API + 3 DockerImageFunctions + UsagePlan +
  ApiKey. References Data for the price-cache Lambda's read+write
  permissions.

The split lets us tear down compute without touching the VPC (saves
the 90s VPC create on next deploy) and tear down API without touching
the DynamoDB cache (preserves cached price data across deploys).

### 4.3 Decisions documented in ADRs

- **ADR-0001 — Foundation VPC design.** 2 AZs not 3 (3rd AZ buys nothing
  for a single EC2 but exposes us to per-AZ NAT bills if anyone enables
  NAT later). Zero NAT gateways (PRIVATE_ISOLATED tier; saves $32-64/mo).
  CloudFront-logs S3 bucket pre-provisioned for Phase 4 to avoid
  refactor.

- **ADR-0002 — Phase 2 compute design.** Container Image Lambda over
  Zip+Layers (numpy + scipy + pandas blow the 250 MB unzipped cap;
  container raises it to 10 GB, scipy import time dominates cold start
  regardless). Single-table DynamoDB key design `TICKER#sym / BAR#granularity#ts`
  with TTL eviction. **REST API not HTTP API** — initially recommended
  HTTP API on cost ($0.13/mo savings at 50K req); flipped to REST after
  weighing the actual feature need (built-in usage_plan + api_key for
  the 1k/day throttle requirement). Cold-start mitigation: scheduled
  CloudWatch warmer planned, SnapStart deferred until P95 misses 1 s,
  Provisioned Concurrency abandoned (would blow the budget).

## 5. Lessons learned

These are the bugs that real deploys surfaced. Code-only review wouldn't
have caught any of them. Each is committed as a guard or documented for
the future.

1. **EC2 SecurityGroup descriptions reject non-ASCII.** First Phase 1
   deploy failed because the SG description contained an em-dash `—`.
   CloudFormation auto-rolled back cleanly (no orphan resources, no
   spend). Lesson: lint passes don't model service-level constraints;
   only real CFN does. Fix committed (`22745cb`); future commits screen
   for non-ASCII in any string property bound to a CFN Resource.

2. **AL2023's bundled docker buildx is 0.12; compose v2.31 wants 0.17+.**
   First Phase 2 deploy succeeded at the CDK layer but the on-EC2 image
   build failed with `compose build requires buildx 0.17.0 or later`.
   Fix committed (`a265d44`): user-data downloads buildx v0.18.0
   alongside compose. Lesson: AMI bundles drift; pin tooling
   versions in IaC, not by trusting the AMI default.

3. **`python:3.10-slim` doesn't include curl.** The compose healthcheck
   used `curl` — exec'd, exit 127, container stuck "starting" forever,
   Caddy's `depends_on: service_healthy` blocked Caddy from ever
   coming up. Fix committed: switch to `python -c
   'import urllib.request; urllib.request.urlopen(...)'` which uses
   only what the base image already ships. Lesson: healthchecks should
   use base-image-native tools.

4. **Cross-arch Lambda images.** M-series Mac builds arm64 by default
   but Lambda is configured for x86_64. risk-calculator + options-pricer
   pushed silently as arm64 (would crash at first invoke with
   `Runtime.InvalidEntrypoint`); price-cache failed at `pip install`
   because numpy 2.4 has no arm64 wheel and the Lambda base image has
   no compiler. Fix committed (`0b6a33d`):
   `platform=ecr_assets.Platform.LINUX_AMD64` on every
   `DockerImageCode.from_image_asset`; numpy pinned to 1.26.4 in
   price-cache to defeat yfinance pulling numpy 2.x.

5. **Eager package init forced cross-service transitive deps.** The
   second Phase 2 deploy succeeded but `/greeks` returned HTTP 502 with
   `Runtime.ImportModuleError: No module named 'pandas'`. Root cause:
   `libs/mindmarket_core/__init__.py` did `from . import var, ...` and
   `var.py` imports pandas — but options-pricer deliberately omitted
   pandas to save 70 MB of image size. Eager init forced every
   consumer to install every transitive dep. Fix committed: empty
   `__init__.py` + docstring telling consumers to import specific
   submodules. Lesson: lazy package init when sub-modules have
   divergent transitive deps; eager init is a coupling hazard.

6. **yfinance ↔ Yahoo Finance API drift.** `/price/AAPL` returned
   `JSONDecodeError: Expecting value: line 1 column 1` for every
   ticker. yfinance pinned 6 months ago, Yahoo's HTML/API contract
   shifted. Architecture itself is sound (Lambda → DDB chain proven
   by the well-formed error response), but the data source is
   fragile. Triaged to Phase 4 cost-optimization where we evaluate
   FMP Starter ($19/mo) or Polygon Stocks Starter ($29/mo) as the
   primary feed. Lesson: external free data sources are fragile;
   production needs a paid feed or a fallback layer.

## 6. Strategic priorities

Ordered by leverage. Each line cites the LP it speaks to.

1. **Phase 4 polish — 6-pager (this doc), STAR stories, demo video.**
   Existing material from Phase 1+2 already supports 6 STAR stories;
   2 more (Auth integration, dedup) come from this week. Highest
   leverage on the original Amazon SWE goal.
   *(Bias for Action; Deliver Results)*

2. **`mindmarket.app` DNS + ACME-issued cert end-to-end.** Eliminates
   the "site can't be reached" embarrassment when a recruiter clicks
   the link in a resume. Stack already supports it via the
   `DOMAIN=mindmarket.app` env override on `deploy-phase-1.sh`;
   waiting only on DNS configuration at Porkbun.
   *(Deliver Results)*

3. **Phase 4 cost optimization sweep — measure, propose, implement
   the best 2.** Real numbers from Cost Explorer + before/after diff,
   not theoretical. Likely candidates: arm64 Lambda images
   (~10% save on compute time), DynamoDB DAX in front of PriceCache
   (kills repeat-read costs at higher scale).
   *(Frugality; Are Right, A Lot)*

4. **AWS Phase 3 if a recruiter pushes for "more"** — Cognito,
   async-backtest pipeline (SQS + worker Lambda), CloudWatch
   dashboard + alarms with 6-row runbook. None of these are unique
   to this project; they're standard AWS hygiene patterns. Worth
   doing only if Phase 4 alone doesn't close a job offer.

5. **Stripe credits + paid plan** — only if a real user asks. Without
   a user, Stripe integration is "for show" and trivializes the more
   substantial Phase 1+2 work in a recruiter's read.

## Appendix — FAQ

**Why Streamlit at all? Why not React + FastAPI?**
The product is a quant analytics tool, not a transactional app. Every
page is a dashboard with computed Greeks, charts, and tables. React +
FastAPI would buy us prettier UX and zero of the analytical functionality.
The 4 weeks are better spent on the AWS migration story than rebuilding
in JavaScript what already works in Python.

**Why two Streamlit deployments — Streamlit Cloud and AWS?**
The free Streamlit Cloud (`mindmarketai.streamlit.app`) is the always-on
public demo. The AWS-hosted instance at `mindmarket.app` is the demo we
spin up for recruiter demos and tear down to save credits. Same source,
same `Dockerfile`, different deploy targets. The AWS instance is the
one that gets the active-portfolio + Auth integration tested first
because it's the production-shape rehearsal.

**Why Supabase Auth, not AWS Cognito?**
Free-tier generosity (50K MAU + 500 MB Postgres + RLS, all in one),
Postgres beats DynamoDB for the relational shape of portfolios + holdings,
and Streamlit-Python-only stack means the Cognito JWT validation
plumbing would need to be hand-written. Cognito is the right choice for
the Phase 3 Lambdas if we ever wire them up to use authenticated
clients; for the EC2 Streamlit monolith, Supabase pays for itself in
saved engineering days.

**Why REST API, not HTTP API?**
ADR-0002 covers this. Tl;dr: $0.13/mo cost difference vs. native
`UsagePlan + ApiKey + RequestValidator` that would otherwise be a
hand-rolled Lambda authorizer plus DynamoDB counter. The throttle is a
real Phase 2 requirement; rebuilding it doesn't justify the saving.

**Why no NAT gateways?**
$32/mo each, $64/mo for two AZs. Whole monthly budget is $33. No.
Lambdas live OUTSIDE the VPC by default. If we ever move them inside
(to access RDS or a private endpoint), we add free VPC endpoints
(S3 gateway, DynamoDB gateway) plus interface endpoints at $7.20/mo
each — still cheaper than NAT past 1 endpoint, much cheaper past 4.

**What's the worst-case spend if I forget to destroy?**
EC2 t3.micro at 24/7: $9.30. Attached EIP: $0. Detached EIP after
destroy (operator forgets to release): $3.60/mo. CloudFront not yet
in use: $0. Lambda-API not yet in use after destroy: $0. So a forgotten
destroy costs $9.30/mo, capped by the AWS Budget alarm at $20/mo
(set up pre-deploy, see migration-log entry 2026-04-26).

**Where is the AI agent in this architecture?**
`call_llm()` lives in `app.py`, called by every Streamlit page. Backend
toggles between Anthropic Claude / DeepSeek / local Ollama based on
sidebar config. The 4 tools (VaR, sentiment, transcript analysis,
conditional stress) are method calls into the existing modules — they
weren't extracted into Lambda for Phase 2 because they're per-keystroke
interactive (latency budget < 200 ms after warm). Phase 3 may revisit
if we add Bedrock as a backend.

**What happens if Supabase goes down mid-demo?**
`libs/auth/active_portfolio.py:_resolve()` catches every exception
from the Supabase client and falls back to the hardcoded portfolio.
The user sees the demo data instead of theirs, but the dashboard
keeps working. Verified by `test_active_falls_back_when_db_query_fails`
in `tests/unit/test_auth_portfolios.py`.
