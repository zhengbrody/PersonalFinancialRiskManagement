# MindMarket AI - Technology Stack & Skills

> Portfolio Risk Management SaaS | Quantitative Finance Application
> Live at **https://mindmarket.app**

---

## Project Overview

An institutional-grade portfolio risk analytics SaaS for retail investors: real-time
risk calculation, AI-powered market intelligence, standalone ticker research, and an
AI portfolio Copilot — all behind a strict "the LLM never invents a number"
deterministic-engine boundary.

The platform runs on a **split stack**: a Next.js + TypeScript frontend (the primary
UI) talking to a FastAPI + Pydantic backend. It began as a Streamlit app, which was
**fully retired in 2026-06** once every surface had been ported to the split stack.

**Scale**: 1,342 backend tests + 590 frontend tests + 869 legacy-engine tests + 74 Playwright E2E | 10+
external API integrations | envelope-shaped `{data, error, meta}` API | English-only UI

---

## 0. Architecture — Split Stack (Next.js + FastAPI)

The product was migrated from a Streamlit-only app to a split stack in 2026-05;
production traffic is served by the Next.js frontend. The legacy Streamlit app was
**fully retired on 2026-06-23** — its UI code, the backend's dependency on Streamlit,
and the running `/legacy` container were all removed (recoverable from git history).

```
internet → Cloudflare → Caddy :80/443 ─┬─► /          → Next.js   :3000   (primary UI)
                                        └─► /api/v1/*  → FastAPI   :8000   (API)
```

| Tier | Technology | Role |
|------|-----------|------|
| **Frontend (primary)** | Next.js 15 (App Router) + TypeScript + Tailwind + shadcn-style primitives + Recharts | The live UI at mindmarket.app — standalone output, SSR/SEO, market-synced theme |
| **Backend (API)** | FastAPI (Python 3.12) + Pydantic v2 | Envelope-shaped `{data, error, meta}` endpoints; reuses the quant engine verbatim |
| **MCP server** | Anthropic MCP (stdio) | 10 tools exposing scoring / market / research / portfolio-risk to Claude |

**Trust-boundary layering** (the LLM-never-invents-a-number rule):
- `domain/` — Pydantic v2 input validation at the trust boundary (rejects NaN/Inf,
  malformed tickers, formula-injection strings).
- `engine/quant.py` + `libs/mindmarket_core/` — pure math (NumPy/SciPy/pandas). No LLM,
  no network, no session state.
- `agents/` — typed agent output with `grounded_in` attribution.
- The AI layer only **rephrases** deterministic skeletons into prose; severity,
  numbers, and actions are always the engine's.

---

## 1. Quantitative Finance & Risk Analytics

| Skill | Implementation |
|-------|---------------|
| **Monte Carlo VaR/CVaR** | Fixed 10,000-path simulation for Value-at-Risk and Expected Shortfall (95th/99th percentile) — `risk_engine.py` and `libs/mindmarket_core/var.py` both default to 10,000 and no live caller overrides it (the adjustable path count was a Streamlit-sidebar control, retired with that UI) |
| **EWMA Covariance** | Exponentially-weighted moving average (lambda=0.94) for dynamic correlation modeling |
| **Multi-Factor Beta Analysis** | OLS regression against SPY, QQQ, GLD, TLT, IWM, VTV with statistical significance (t-stats, p-values, R-squared) |
| **Efficient Frontier** | Markowitz portfolio optimization via `scipy.optimize.minimize` (min variance, max Sharpe) |
| **Stress Testing** | Scenario analysis with asset-level loss attribution, conditional multivariate normal propagation; real-crisis historical replay (COVID-19, 2022, 2018Q4, GFC) |
| **Drawdown Analysis** | Maximum drawdown, duration statistics, rolling drawdown series |
| **Component VaR** | Euler decomposition and risk attribution by asset |
| **Performance Attribution** | Brinson + factor (PCA) attribution with benchmark-labeled factors |
| **VaR Backtesting** | Gaussian 1-day VaR vs realised breach count (Kupiec-style) + empirical return histogram |
| **Margin / Leverage** | Cash-drag + margin-leverage folded into score & report; equity ratio, distance-to-call |
| **Concentration** | Top-name / top-5 / HHI / effective holdings + sector roll-up |
| **DCF Valuation** | CAPM-based discount rate, multi-stage growth model |
| **Macro Sensitivity** | Beta exposure to interest rates, USD index, crude oil |
| **Liquidity Risk** | Days-to-liquidate based on 30-day average daily volume (ADV) |
| **Regime Detection** | HMM (Gaussian mixture EM), volatility ratio, SMA trend, composite voting |

---

## 2. Options Analytics

| Feature | Detail |
|---------|--------|
| Pricing | Black-Scholes analytical pricing with Newton-Raphson IV solver |
| Greeks | Delta, Gamma, Theta, Vega, Rho — per-contract and portfolio-level roll-up |
| Strategies | Multi-leg netting (bull/bear call & put spreads, straddle, strangle, custom) with bounded max-loss/max-gain and break-evens |
| Risk integration | Delta-equivalent overlay folds options into the equity VaR / factor / concentration machinery (deterministic) |
| Reprice grid | Full Black-Scholes underlying × IV × time stress grid (captures gamma/vega/theta) |
| Exposure & flags | Net/gross delta, expiry ladder, per-underlying exposure, deterministic risk flags (short gamma, uncovered short call, under-collateralized, concentrated expiry) |

---

## 3. Frontend Application Development — Next.js

### UI (primary) — Next.js 15 + TypeScript
- App Router with standalone output; **40 route segments** (`page.tsx` files).
  Authed cockpit: **`/analyze`** (the primary signed-in surface — a five-stage
  URL-addressable workspace), plus `/score`, `/risk`, `/scenarios`, `/quant`,
  `/research`, `/markets`, `/copilot`, `/institutions`, `/portfolios`,
  `/settings`, `/admin`. Public/SEO: `/`, `/product`, `/learn/*`,
  `/resources`, `/risk-today`, `/methodology/health-score`,
  `/methodology/regime-model`, `/demo-risk-check`, `/share/risk-card`,
  `/legal/*`, `/pricing` (billing UI hidden during free beta).
- Tailwind CSS + shadcn-style primitives (Button / Card / Input / Tabs / DataTable /
  ScoreGauge / KPI / Badge).
- **Recharts** for all data visualization (time-series, bar, donut, sparkline, payoff).
- Strict typed API client: every response validated against the `{data, error, meta}`
  envelope with zod; `openapi-typescript`-generated API types.
- Market-synced day/night theme (light by day / dark overnight, ET, DST-correct).
- SSR/SEO: static prerendered marketing + `/learn` topic pages, JSON-LD
  (Organization / SoftwareApplication / FAQ / Breadcrumb), OG cards, sitemap/robots.
- Mobile-first responsive layout (grouped desktop nav → hamburger below md).
- AI Copilot: streaming SSE chat (token-by-token), tool-use, floating widget,
  intent-routed structured Q&A.

### Backend Application — FastAPI + Pydantic v2
- **89 paths / 98 operations** across 23 routers (measured from the committed
  `openapi.json`), all envelope-shaped `{data, error, meta}`; per-route JWT dependency.
- Supabase RLS JWT forwarding; fail-closed auth (503 on JWKS outage, never silent
  downgrade).
- Reuses the legacy quant engine modules verbatim — one source of truth for the math.
- Fail-soft external-data adapters (yfinance / FMP / Massive / FRED / SEC) behind
  short in-process TTL caches; provider provenance surfaced to the UI.
- Credit-metered AI usage with per-call cost recording; in-process TTL+LRU AI cache.

### Concurrency
- `ThreadPoolExecutor` for parallel data fetching (per-holding sentiment, batch
  scoring); `concurrent.futures.as_completed` for result aggregation.

---

## 4. AI/LLM Integration

| Technology | Usage |
|-----------|-------|
| **DeepSeek API** (default, via the OpenAI client) | `MINDMARKET_LLM_PROVIDER` defaults to `deepseek` (model `deepseek-v4-flash`, reasoning disabled) — risk briefing, market sentiment, scenario narrative, ticker verdict, Copilot. Real `/user/balance` metering feeds the owner dashboard |
| **Anthropic Claude API** (alternate) | Swap in with `MINDMARKET_LLM_PROVIDER=anthropic`, no code change — Sonnet/Haiku routing by token budget. These two are the only backends `services/llm_client.py` implements |
| **Deterministic boundary** | `build_skeleton()` derives severity/findings/actions in pure Python; the LLM only **rephrases** into JSON. No-key / quota / bad-JSON → deterministic template. The model never originates a number. |
| **Grounded attribution** | Every AI answer ships `grounded_in` / source-labeled evidence; figures cite the engine output or a named data provider. |
| **Forced reply language** | Copilot detects a Chinese question (deterministic CJK heuristic) and forces a Chinese LLM reply; the **UI itself is English-only**. |
| **Telemetry** | Per-call tokens / cost / latency / cache-hit / eval signals (advice/grounding heuristics) recorded for the owner dashboard. |

---

## 5. Data Engineering & ETL

| Component | Detail |
|-----------|--------|
| **Data Sources** | Massive (Polygon-style — primary for US prices/OHLC/history), Yahoo Finance (yfinance — free fallback that fills whatever Massive doesn't return), Financial Modeling Prep (FMP — fundamentals/analyst/peers), FRED + US Treasury (macro), SEC EDGAR (13F / Form-4), CNN Fear & Greed, RSS feeds |
| **Provider strategy** | Registry-declared roles (`services/providers/registry.py`): Massive primary for prices, FMP primary for fundamentals, FRED/Treasury for macro, SEC for filings — **yfinance is FALLBACK only**. `market_data.get_price_history` tries Massive first when configured and lets yfinance fill the remainder; every figure carries its actual source |
| **Data Pipeline** | Per-ticker error isolation, multi-point data-quality validation; everything fail-soft (a provider blip degrades to a fallback, never a 5xx) |
| **Caching** | In-process TTL caches per domain (price / history / fundamentals / macro) |
| **Data Validation** | Min data points, missing-rate, negative-price, extreme-return and suspension detection; finite-guards on all serialized numbers |
| **Data Cleaning** | Forward-fill, interpolation for small gaps, winsorization (1st-99th percentile) |

---

## 6. Data Visualization

- **Recharts**: equity-curve / drawdown time-series, risk-driver & factor
  bar charts, allocation donut, KPI sparklines, options payoff curves, scenario sweeps,
  efficient-frontier scatter, VaR histogram — all theme-aware (CSS variables, light+dark).
  (Plotly charts lived in the old Streamlit workbench, retired 2026-06-23.)

---

## 7. Reporting & Export

| Tool | Usage |
|------|-------|
| **Self-contained HTML reports** | Backend renders portfolio / ticker / options reports as one printable HTML doc (inline CSS + `@media print`, server-generated inline SVG payoff, every field HTML-escaped) → browser Save-as-PDF |

---

## 8. Testing & Code Quality

| Tool | Usage |
|------|-------|
| **pytest** | 1,342 backend tests + 869 legacy-engine unit/integration tests |
| **Vitest** | 590 frontend tests (React Testing Library) |
| **tsc / ESLint** | Strict TypeScript type-checking + linting on the frontend |
| **Black / Ruff** | Python formatting (100-char) + fast linting (pycodestyle, pyflakes, isort) |
| **MyPy** | Static type checking on core modules |
| **pre-commit** | Git hooks: black, ruff, trailing whitespace, YAML check, large-file prevention |

| **Playwright** | 74 E2E tests (mocked-API suite, run on both a desktop and a Pixel-7 mobile project) + a gated nightly real-auth smoke against production |

> Test counts are measured, not hardcoded: `python -m pytest backend/tests/ --collect-only -q`
> (backend), `npx vitest list` (frontend), `python -m pytest tests/ --collect-only -q` (legacy),
> `npx playwright test --list` (E2E).

---

## 9. DevOps & Infrastructure

| Component | Detail |
|-----------|--------|
| **Docker** | Separate `frontend/Dockerfile` (Next.js standalone) + `backend/Dockerfile` (Python 3.12) |
| **docker-compose** | `compose.split.yml` (backend + frontend, GHCR images) + `compose.aws.yml` (Caddy / TLS) orchestrate the live production stack |
| **GitHub Actions CI/CD** | Builds frontend + backend images on GH runners → pushes to **GHCR** (`ghcr.io/zhengbrody/mindmarket-{frontend,backend}`); runs pytest / vitest / black / ruff / tsc / eslint |
| **Pull-only deploys** | EC2 pulls prebuilt images from GHCR (never builds on-box — the t3.micro is RAM-bound); zero-build, fast rollback |
| **Cloudflare** | DNS + CDN + edge WAF/rate-limiting in front of EC2; origin IP hidden, AWS SG locked to Cloudflare IP ranges |
| **AWS EC2 + Caddy + Cloudflare Origin CA** | Production at `https://mindmarket.app` (t3.micro + 1 GB swap). Origin TLS is a 15-year Cloudflare Origin CA cert pinned via `tls` in the `Caddyfile` — it retired ACME behind the proxy; the old Let's Encrypt cert survives only as an unused rollback in the `caddy_data` volume |

---

## 10. Observability

| Tool | Usage |
|------|-------|
| **Sentry** | Error tracking on **both** stacks (backend `sentry-sdk[fastapi]` auto-captures unhandled 500s; frontend `@sentry/nextjs` v8 client/server/edge) — errors-only, prod-only |
| **PostHog** | Funnel analytics (signup → score → copilot) with autocapture; events are privacy-redacted (no tickers, no $, no holdings, no prompts) |
| **Owner dashboard** | Live in-process API-call metrics (per-route HTTP + per-provider outcomes), AI cost by model, and DeepSeek/Claude balance monitoring |
| **structlog + python-json-logger** | Structured JSON logging with context binding; rotating file handler |

---

## 11. Error Handling & Resilience

- Centralized error categorization (JSON decode, connection, insufficient data, linear
  algebra, weight errors) with user-friendly recovery suggestions.
- Strict envelope contract validated at the frontend boundary — backend shape-drift is
  caught (zod) instead of becoming an `undefined` crash deep in a component.
- Fail-soft external-data adapters: a Supabase / provider blip degrades to a fallback,
  never a 5xx.
- Retry logic with exponential backoff for API calls; expired-cache fallback on
  download failure; fallback LLM providers when the primary is unavailable.

---

## 12. Numerical Stability

- Log-space GMM E-step (regime detector) to avoid underflow.
- Zero-division guards across Sharpe / Sortino / MaxDD (backtest engine).
- EWMA covariance edge cases, NaN safety (risk engine).
- IV solver wider bracket + strike ordering guards (options analytics).
- Log-space cumulative returns (performance attribution).
- Leverage- & cash-invariant headline Sharpe (consistent across Health Score & Risk
  Report).

---

## 13. Auth, Multi-Tenancy & Billing

| Component | Detail |
|-----------|--------|
| **Supabase** | Postgres + Auth (email/password + Google OAuth PKCE) + Row-Level Security + Edge Functions |
| **Multi-tenancy** | Per-user `portfolios` / `holdings` tables; `active_portfolio` resolver; RLS so users only see their own data |
| **Stripe** | Checkout + Customer Portal + webhook (Supabase Edge Function). Currently **Test mode / free-beta** (billing UI gated behind a flag; metering infra intact) |
| **Credit metering** | Usage metered in credits (1 credit = $0.01 of real LLM cost), per-plan monthly budgets; owner-unlimited |

---

## 14. External APIs Integrated

| API | Purpose |
|-----|---------|
| Massive (Polygon-style) | **Primary** US EOD price + daily history |
| Yahoo Finance (yfinance) | **Fallback** prices + free fundamentals, news, volume fill-in |
| DeepSeek | AI narratives, Copilot, ticker verdict (**default LLM**) + live balance metering |
| Anthropic Claude | Alternate LLM backend, selected by `MINDMARKET_LLM_PROVIDER=anthropic` |
| Financial Modeling Prep (FMP) | Fundamentals, ratios, growth, analyst consensus, peers, insider, news |
| FRED + US Treasury | Macro series + yield curve (free) |
| SEC EDGAR | 13F institutional filings + Form-4 insider transactions |
| CNN Fear & Greed | Market sentiment index |
| RSS Feeds | Reuters, CNBC, MarketWatch, FT, Bloomberg macro news |
| Supabase | Auth + Postgres + RLS + Edge Functions |
| Stripe | Subscription billing (Test mode) |

---

## 15. Design Patterns & Architecture

- **Layered trust boundary**: `domain/` (Pydantic validation) → `engine/` + `libs/mindmarket_core/`
  (pure math) → `agents/` (typed, grounded AI output) → FastAPI (envelope) → Next.js (typed client).
- **Adapter Pattern**: thin fail-soft `services/*` wrappers over each data provider + the legacy engine.
- **Skeleton → LLM template**: deterministic `build_skeleton()` + `render_template()` fallback;
  the LLM only rephrases (risk-explain / options-explain / verdict).
- **Strategy Pattern**: both LLM backends (DeepSeek default / Claude alternate) unified behind one stateless client, selected by env var.
- **Provider Pattern**: `ProviderResult{data, source, as_of, coverage, warnings}` carries provenance end-to-end.
- **Separation of Concerns**: Frontend (Next.js/TS) / API (FastAPI) / Domain math (engine) /
  Data layer (services/providers) / Cross-cutting (auth, billing, logging, telemetry).

---

## Key Technical Highlights

1. **Split-stack migration**: Streamlit-only → Next.js (TS) + FastAPI (Python 3.12), live in production (Streamlit fully retired 2026-06 after every surface was ported).
2. **Quantitative Finance**: VaR, Monte Carlo, EWMA, Markowitz optimization, multi-factor models, options Greeks, regime detection.
3. **AI with a hard truth boundary**: the LLM never invents a number — it rephrases deterministic engine output, with grounded attribution and per-call telemetry.
4. **Data engineering**: multi-source smart-hybrid ETL with provenance, fail-soft adapters, per-domain caching.
5. **Production-ready**: GHCR image pipeline + pull-only deploys, Cloudflare + Caddy + a pinned Cloudflare Origin CA cert, Sentry + PostHog observability, 1,342 + 590 + 869 tests plus 74 Playwright E2E.
6. **Full-stack engineering**: typed end-to-end (Pydantic v2 ↔ zod / openapi-typescript), Supabase multi-tenancy + RLS, Stripe billing, MCP server.
