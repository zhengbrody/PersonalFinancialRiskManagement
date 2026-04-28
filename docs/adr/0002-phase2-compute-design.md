# ADR-0002 — Phase 2 Compute Design (Lambda + API Gateway + DynamoDB)

- **Status:** Accepted (overrules HTTP API recommendation in earlier draft)
- **Date:** 2026-04-27
- **Phase:** 2 (extract compute to Lambda)

> Research drafted in parallel with Phase 1 deploy. Numbers verified against
> current AWS pricing and PyPI wheel sizes. Final decision flipped from
> HTTP API to **REST API** — see "API Gateway type — final decision" below.

## Context

Phase 1 puts a single Streamlit + Docker on EC2. Phase 2 must extract the
compute-heavy, stateless work (`risk_engine.calculate_var()`,
`options_engine` Black-Scholes, `data_provider` yfinance fronting) into
Lambda functions exposed via API Gateway, with DynamoDB as the cache.

Constraint: AWS Free Plan budget (~$33/mo total). The new Free Plan model
gives credits, not service quotas, so every choice burns budget.

## Decisions

### 1. Container Image Lambda over Zip + Layers

Verified wheel sizes on Linux x86_64 (manylinux): numpy ~56 MB, scipy ~97 MB,
pandas ~70 MB. Once you add `pyarrow` (pulled by recent pandas),
`python-dateutil`, `pytz`, our 3 source modules (~140 KB), and the AWS SDK,
the deployment package lands at **~280–310 MB compressed → ~520 MB unzipped**.

Lambda zip+layers limit is **250 MB unzipped** (function + layers combined).
Hard fail.

Container Image Lambda allows up to **10 GB**, uses
`public.ecr.aws/lambda/python:3.11` as the base (~580 MB), final image ~900 MB.
Cold-start delta vs zip is **~50–150 ms** — Lambda streams images from a
cached layer. Scipy import time (~600 ms) dominates regardless of packaging.

**Cost:** ECR free tier is 500 MB private storage; ~400 MB overage = $0.04/mo.
Build time: ~3 min cached, ~6 min cold (GitHub Actions).

### 2. DynamoDB single-table key design

```
pk = "TICKER#<symbol>"
sk = "BAR#<granularity>#<iso-timestamp>"

Examples:
  pk = "TICKER#AAPL", sk = "BAR#1D#2024-01-15"
  pk = "TICKER#AAPL", sk = "BAR#5M#2024-01-15T14:30Z"

TTL attribute `expiresAt`:
  - intraday bars  →  1 day
  - end-of-day     → 30 days
  - historical 1Y+ →  no TTL (keep forever)
```

**Hot-partition risk:** SPY/QQQ/AAPL get 100× the writes of small caps.
DynamoDB caps a single partition at 1000 WCU / 3000 RCU. Single-tenant Phase 2
(<100 users) won't approach this; if we ever do, shard by
`pk = "TICKER#AAPL#<dayhash%4>"` — Phase 4 ADR.

**Don't** split hot/cold tables — TTL on the same item handles eviction.

**Query patterns:**
- "All bars for ticker X over date range Y" → native `Query` on pk+sk
  `BETWEEN`. No GSI needed.
- "All tickers' close on date Y" → **GSI required**:
  `gsi1pk = "DATE#2024-01-15"`, `gsi1sk = "TICKER#AAPL"`.
  Doubles write cost (~$0.50/mo at our scale). Only build it when the
  cross-sectional query lands in product UI.

### 3. API Gateway type — final decision: **REST API**

**Pricing per 1M requests:**

| Gateway type | Cost / 1M | Our 50K/mo | Built-in throttle |
|---|---|---|---|
| **REST API** | **$3.50** | **$0.18** | ✅ usage plans + API keys |
| HTTP API | $1.00 | $0.05 | ❌ — need Lambda authorizer |
| AppSync | $4.00 | $0.20 | n/a (GraphQL) |

Initial draft recommended HTTP API on cost. **Decision flipped to REST API**
after weighing the actual feature need:

- Phase 2 spec mandates "1000 req/day throttle" to prevent runaway-cost.
  REST API gives this **declaratively** via `UsagePlan` + `ApiKey`
  resources in CDK. HTTP API gateway has no such concept; we'd
  hand-roll a Lambda authorizer backed by a DynamoDB counter row,
  TTL=24h, conditional update on increment. ~50 lines + ~5 ms latency
  per request + a new failure mode (DDB throttle = whole API down).

- Cost difference at our scale (50K req/mo) is **$0.13/mo** —
  rounding error against the budget.

- REST API's `RequestValidator` does JSON-schema validation at the
  gateway, before Lambda invocation. We pay nothing for malformed
  requests. HTTP API has no equivalent.

- Cognito authorizer (Phase 3) works on both; not a tiebreaker.

- Latency cost (REST adds ~50 ms gateway overhead vs HTTP's ~20 ms)
  is acceptable — we already budget P95 under 1 s and our compute
  dominates (scipy import alone is ~600 ms cold).

**Rejected alternative:** HTTP API + Lambda authorizer. Rebuilding
something AWS already ships well, on a budget that doesn't justify
optimizing the $0.13.

### 4. Cold start mitigation, in escalation order

(a) **CloudWatch Events warmer** — start here. Schedule a `rate(5 minutes)`
rule per Lambda that invokes with `{"warmer": true}` payload; the handler
short-circuits and returns immediately. Costs ~8,640 invocations/mo —
covered by the 1M free-tier. Kills 90 % of user-visible cold starts in
practice.

(b) **Python SnapStart** — confirmed Python 3.12+ (GA Nov 2024). Free.
Restores from a snapshot, saving ~200–400 ms on Python (smaller delta than
on Java because Python startup is mostly imports, which SnapStart freezes
post-import). Apply only to risk-calculator if (a) doesn't get P95 under 1s.

(c) **Provisioned Concurrency** — ABANDONED. $14/mo per concurrency unit
per Lambda. With 3 Lambdas + 1 unit each = $42/mo, **above our entire
budget for one feature**. Revisit only when paying customers exist.

(d) **Smaller base image (Alpine)** — ABANDONED. Public AWS Lambda Python
base is Amazon Linux glibc; Alpine uses musl, which breaks the manylinux
numpy/scipy wheels (we'd have to compile from source on every build,
adding 15+ minutes). 150 MB savings not worth it.

## Phase 2 estimated total cost

| Service | Estimate |
|---|---|
| Lambda (50K req/mo, 3 GB mem, ~2s avg) | $0 (free tier covers) |
| ECR (one private repo, ~900 MB) | $0.04 |
| DynamoDB on-demand | ~$2 |
| REST API (50K req) + usage plan | $0.18 |
| CloudWatch logs + warmer + metrics | ~$1 |
| Data transfer out | ~$2 |
| Buffer for spikes | ~$3 |
| **Total** | **~$8/mo** |

Combined with Phase 1's ~$9/mo (when EC2 running), Phase 1+2 sits at ~$17/mo
when fully deployed. With our destroy-when-idle pattern, actual burn is
closer to ~$5–8/mo for active demo days.

## Open questions (resolve before implementing)

1. **Streaming responses** — Lambda Response Streaming exists; Streamlit
   on EC2 currently reads results synchronously. If Phase 2 keeps the
   sync POST /var pattern, we don't need streaming. Confirm with API
   shape before building.
2. **Cross-region disaster recovery** — out of scope for Phase 2. Note
   that DynamoDB Global Tables would change the cost picture significantly.
3. **VPC for Lambda** — Phase 2 default keeps Lambdas OUTSIDE the VPC
   (faster cold start, no need for NAT). If we later need to access
   private resources, switch to VPC-attached + add VPC endpoints
   (already provisioned in FoundationStack as the private tier exists
   but is empty).
