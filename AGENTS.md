# MindMarket AI — Project Context & Decisions

> This file is the single source of truth for project context across Codex sessions.
> Last updated: 2026-05-11

---

## 1. Project Overview

**MindMarket AI** is an institutional-grade portfolio risk analytics platform built with Streamlit.

- **Current state**: Functional multi-page Streamlit app with 10 pages, deployed at `https://mindmarketai.streamlit.app`
- **Target state**: Public-facing SaaS at **mindmarket.ai** where individual users register, input their own portfolios, and get AI-powered risk analysis
- **Core engine**: Monte Carlo VaR/CVaR, factor models (6-factor + macro), stress testing, performance attribution, regime detection
- **AI integration**: LLM-powered summaries on every page (Codex / DeepSeek / Ollama backends)
- **Languages**: English + Chinese (i18n via `i18n.py`)
- **Owner**: zhengbrody (GitHub)

### Key Files
- `app.py` — Main Streamlit entry, `call_llm()`, `fetch_live_weights()`, color constants
- `portfolio_config.py` — Holdings, margin loan, cost basis (currently hardcoded, will become per-user DB)
- `risk_engine.py` — `RiskEngine` class + `RiskReport` dataclass
- `market_intelligence.py` — Fundamentals, VIX, yield curve, DCF, insider signals, technicals, `fetch_ticker_research()`
- `ui/components.py` — Design system: `render_kpi_row()`, `render_section()`, `render_ai_digest()`, `render_chart()`, `render_pt_range_bar()`
- `ui/tokens.py` — Design tokens (colors, spacing, typography)
- `ui/shared_sidebar.py` — Shared sidebar with provider detection, portfolio config, analysis params

### Pages
| Page | Purpose |
|------|---------|
| 1_Overview | Executive dashboard: KPIs, AI digest, cumulative returns, drawdown |
| 2_Risk | VaR/CVaR, component VaR, factor betas, stress testing (3 modes) |
| 3_Markets | Market regime (VIX/Yield/F&G), macro news, AI sentiment, earnings call AI |
| 4_Portfolio | Efficient frontier, trade blotter, scenario simulator (-30%~+30%), cash deployment, margin monitor |
| 5_TradingView | Embedded TradingView charts |
| 6_Guided_Analysis | Question-first workflow: maps user goals to pages and priority metrics |
| 7_Trading_Floor | Bloomberg Terminal style: regime, sectors, movers, next-read routing |
| 8_Institutions | SEC 13F smart money, institution deep dive, conviction and crowding analysis |
| 9_Quant_Lab | Backtesting, performance attribution, regime analysis |
| 10_Ticker_Research | **Standalone** any-ticker search: fundamentals, valuation, technicals, insider, institutional, AI recommendation |

---

## 2. Technical Decisions Made (This Session)

### Architecture
| Decision | Rationale |
|----------|-----------|
| `portfolio_config.py` stores `TOTAL_COST_BASIS = 19700` | User's principal tracking; editable locally, shows P&L everywhere |
| `_pc.MARGIN_LOAN` referenced via module, not re-exported from app.py | Avoids stale imports; hot-reload via `importlib.reload()` |
| `render_pt_range_bar()` uses single-line HTML concatenation | Streamlit markdown treats 4+ space indentation as code blocks |
| Ollama auto-detection: probe `localhost:11434` once per session | Hide Ollama from provider list if unreachable (cloud/preview) |
| Merged "Refresh Live Data" + "Run Analysis" into one button | Reduce user friction; secondary "Run with Current Weights" for manual JSON edits |
| AI digests on ALL pages (1-9) with try/except fallback | Each page has LLM summary with static fallback on failure |
| Retired the user-facing Options page; replaced page 6 with Guided Analysis | Options data quality wasn't reliable enough for primary UX; navigation now starts from user goals |

### Deduplication
| What was duplicated | Resolution |
|---------------------|------------|
| Ticker Deep Dive (page 3) vs Ticker Research (page 10) | Removed from page 3; replaced with redirect card to page 10 |
| Options Flow Scanner (page 7) vs Institutions (page 8) | Ultimately removed from the user workflow; page 7 now routes users to the next relevant analysis instead |
| `fetch_price_targets_fmp()` called twice in page 3 | Eliminated with the ticker deep dive removal |

### Bug Fixes
| Bug | File | Fix |
|-----|------|-----|
| `from app import MARGIN_LOAN` — app.py doesn't export it | pages/1_Overview.py | Removed unused import |
| `smart_money_data` never written to session_state | pages/8_Institutions.py | Added `st.session_state["smart_money_data"] = signals` after compute |
| AI digest rendered twice on button click | pages/10_Ticker_Research.py | Changed to `elif` branch (button render vs cached render) |
| RSI/SMA `.iloc[-1]` returns NaN → displays "nan" | pages/10_Ticker_Research.py | Added NaN guard before `float()` conversion |
| `build_sentiment_context` imported but unused | pages/3_Markets.py | Removed dead import |
| Sidebar duplicate render (`StreamlitDuplicateElementKey`) | ui/shared_sidebar.py | Fixed guard using `get_script_run_ctx().script_run_id` |
| HTML rendered as raw text in price target bar | ui/components.py | Rewrote HTML as single-line string concatenation (no indentation) |
| Historical Portfolio Value used gross market value, not cost-basis P&L | pages/1_Overview.py | Corrected formula; regression test added |
| Stress test ignored user-supplied `market_shock`, always used -10% | risk_engine.py | Pass-through user parameter |
| Coverage metric counted tickers, not market value; missing holdings silent | portfolio_config.py | Coverage by market value + explicit missing-ticker list |
| Screenshots drifted (empty-state pages saved as "proof") | scripts/capture_screenshots.py | Verify substrings, drive interactive pages, fail fast on empty state |
| README had stale hardcoded test count (522 vs actual 596) | README.md | Replaced with live CI badge + `pytest --collect-only` command; softened "31 filers" → "~30" |
| All FMP calls failed silently (401/402/403) — user saw empty reports | market_intelligence.py | FMP retired /api/v3/ + /api/v4/ on 2025-08-31. Migrated everything to /stable/ with query params; renamed upgrades-downgrades→grades-historical, stock_peers→stock-peers, earning_call_transcript→earning-call-transcript; quarterly→annual fallback for premium endpoints; added `fmp_validate_key` preflight |
| `_fmp_get` swallowed every HTTP error the same way | market_intelligence.py | Now classifies 401/402/403/429 in logs so UI/diagnostics can distinguish bad key from premium-only |
| Sidebar accepted any string as FMP key (user pasted Apify key, nothing warned) | ui/shared_sidebar.py | Flags keys starting with `apify_`/`sk-`/`sk-ant-` or shorter than 20 chars |
| secrets.toml line 3 had a curly `“` quote — broke TOML parsing of ALL secrets | .streamlit/secrets.toml | Replaced both curly quotes with straight `"` (bytes: E2 80 9C/9D → 22) |
| Markets page duplicated earnings analysis that lives on Ticker Research | pages/3_Markets.py | Removed Earnings Call AI block; Ticker Research's Institutional Analyst Report is the single source |
| Markets sentiment tear sheet showed only SELECTED ticker → misleading | pages/3_Markets.py | Cross-portfolio table + bar chart is primary; selected-ticker detail is a collapsed drill-down |
| Markets sentiment scored holdings serially (~30s for 10 tickers) | pages/3_Markets.py | `ThreadPoolExecutor(max_workers=5)` — ~6s for same batch; progress bar updates as futures resolve |
| FMP + external calls had no 429/5xx retry → "too many requests" bubbled up | market_intelligence.py | Module-level `_http_session` with `urllib3.Retry(total=3, backoff=1.5, force_list=[429,500,502,503,504])`; connection pooling too |
| Options page created too much noise for retail users given current data quality | pages/6_Guided_Analysis.py, pages/7_Trading_Floor.py, pages/8_Institutions.py, ui/shared_sidebar.py, app.py, README.md | Replaced page 6 with a guided analysis hub and removed options-focused UX from the primary user workflow |
| CI red: 9 integration tests mocked `risk_engine.yf.download` — but `risk_engine` stopped importing yfinance in commit 5f5f6fc (DataProvider owns it now) | tests/integration/test_risk_pipeline.py | `@patch("risk_engine.yf.download"...)` → `@patch("data_provider.yf.download"...)` (19 occurrences) |
| `test_adjust_weights` asserted renormalized sum≈1.0 — but the function now deliberately leaves residual as implicit cash (docstring says "do NOT blindly renormalize") | tests/integration/test_risk_pipeline.py | Assertions updated to match current feasibility semantics (caps respected, sum ≤ 1) |
| code-quality CI step red since project inception (57 unformatted files + 379 ruff errors) | repo-wide | `black .` (57 files reformatted); ruff auto-fix (207 of 381); 4 real bugs fixed: pandas import in options_engine.py, 5 duplicate dict keys in CUSIP_TO_TICKER (2 wrong CUSIPs were silently overriding correct INTC/ABBV mappings); ruff config ignores N-rules (project uses uppercase locals/args by design) |
| `pages/3_Markets.py:373` referenced `datetime.now()` after I removed its import | pages/3_Markets.py | Was dead code (`if False else time.time()`); simplified to `time.time()` |
| `_FakeClient` test fixture had duplicate `__init__` (second silently overrode first) | tests/unit/test_analyst_report.py | Collapsed to single `__init__` |

### Numerical Stability (Pre-existing changes committed this session)
- Log-space GMM E-step in `regime_detector.py` (avoids underflow)
- Zero-division guards in `backtest_engine.py` (Sharpe, Sortino, MaxDD)
- EWMA covariance edge cases in `risk_engine.py`
- IV solver wider bracket + strike ordering guards in `options_engine.py`
- Log-space cumulative returns in `performance_attribution.py`
- Consistent `.dropna(subset=["Close"])` in `volatility_scanner.py`

---

## 3. Product Decisions (User's Answers)

### User System
- **Target users**: Individual retail investors who want to understand their own portfolio risk
- **Auth needed**: Yes — users register, log in, manage their own portfolios
- **Auth method**: TBD (Q8 pending — options: email+password, Google OAuth, magic link)

### AI Backend
- **Local/dev**: Free choice (Ollama, Codex, DeepSeek — all three available)
- **Production (mindmarket.ai)**: User's API paid by owner (zhengbrody), wrapped in credit system
- **Model**: Codex API (Anthropic) as primary production backend

### Credit System
- New users get **free credits** (amount TBD — Q10 pending)
- After free credits exhausted → pay to buy more
- Pricing TBD (Q10 pending — e.g., $5 = 100 credits, or $10/month unlimited)
- Each "AI analysis" action = 1 credit deduction

### Deployment
- **Platform**: Railway or Render (B option — ~$5-20/month, custom domain support)
- **Domain**: mindmarket.ai (not yet registered — Q13 pending)
- **Current**: Streamlit Cloud at `mindmarketai.streamlit.app`

### Legal / Branding
- Legal pages (ToS, Privacy, Disclaimer) — later, after product is solid
- Logo/branding — later, not needed now
- Email (contact@mindmarket.ai) — later, after domain purchase

---

## 4. Tech Stack

### Current
| Layer | Technology |
|-------|-----------|
| Frontend | Streamlit (Python) |
| Backend API | FastAPI (in `backend/`) — not yet integrated with main app |
| Risk Engine | Custom Python (NumPy, SciPy, pandas) |
| Charts | Plotly |
| Market Data | yfinance, FMP API, SEC EDGAR, CNN F&G, RSS feeds |
| AI/LLM | Anthropic Codex, DeepSeek, Ollama (local) |
| CI/CD | GitHub Actions (pytest, black, ruff, mypy, codecov) |
| Containerization | Docker + docker-compose |
| Logging | structlog + python-json-logger |

### Planned (Not Yet Implemented)
| Layer | Technology | Rationale |
|-------|-----------|-----------|
| Auth + DB | **Supabase** (recommended) | Free tier, PostgreSQL + Auth + Row Level Security in one |
| Hosting | **Railway** or **Render** | Custom domain, ~$5-20/mo, easy deploy from Git |
| CDN/DNS | **Cloudflare** | Free tier, DDoS protection, SSL, DNS management |
| Error Tracking | **Sentry** | Free tier, crash reporting |
| Domain | **Porkbun** or **Namecheap** | .ai domains ~$50-100/yr |
| Email | **Google Workspace** or **Zoho** (free) | contact@mindmarket.ai |

---

## 5. Open Questions (Pending User Answers)

### Q8: User Registration Method
Options presented:
- **A** — Email + password (traditional)
- **B** — Google/Apple OAuth + email fallback (like ChatGPT)
- **C** — Magic Link (email link, no password)

### Q9: Portfolio Data Input Method
Options presented:
- **A** — Manual input (UI form: ticker + shares)
- **B** — Broker API connection (Robinhood/Moomoo — MCP servers already exist)
- **C** — CSV upload
- **D** — Start with A, add B and C later

### Q10: Credit System Details
Questions:
- How many free credits for new users? (10? 50?)
- What counts as 1 credit? (Each "Generate AI Analysis" click? Each full "Run Analysis"?)
- Pricing model? ($5 = 100 credits? $10/month unlimited?)

### Q11: Database Choice
Options presented:
- **A** — Supabase (recommended — Auth + PostgreSQL + RLS, free tier)
- **B** — Firebase (Google, NoSQL)
- **C** — Self-hosted PostgreSQL on Railway/Render

### Q12: Priority Ranking
User asked to rank 1-5:
1. User registration/login system
2. Credit billing system
3. User custom portfolios (replace hardcoded portfolio_config)
4. Domain registration + deployment
5. Security fixes (API key rotation, CORS fix)

### Q13: Domain Registration
Questions:
- Budget for .ai domain ($50-100/yr)?
- Also register mindmarketai.com (~$10/yr) as backup?
- Have credit card for Porkbun/Namecheap registration?

---

## 6. Security Audit Findings (CRITICAL)

### Immediate Action Required
1. **API keys exposed in git history** — `.streamlit/secrets.toml` was committed with:
   - `ANTHROPIC_API_KEY = "sk-ant-api03-..."` 
   - `FMP_API_KEY = "apify_api_..."` 
   - `DEEPSEEK_API_KEY = "sk-2c786..."` 
   - **Must rotate ALL three keys immediately**
   - Must scrub from git history (`git filter-repo`)

2. **CORS wildcard** — `backend/main.py` has `allow_origins=["*"]`
   - Must restrict to specific domains only

3. **No rate limiting** on API endpoints

4. **No input validation** on weight dictionaries (DoS vector)

---

## 7. Proposed Roadmap

### Phase 0: Security & Cleanup (BLOCKING — before any public deployment)
- [ ] Rotate all 3 compromised API keys
- [ ] Scrub secrets from git history
- [ ] Fix CORS wildcard in backend/main.py
- [ ] Add rate limiting to FastAPI endpoints
- [ ] Commit all current changes cleanly

### Phase 1: User System + Database
- [ ] Set up Supabase project (Auth + PostgreSQL)
- [ ] Implement user registration/login (method per Q8)
- [ ] Create DB schema: users, portfolios, holdings, credits
- [ ] Replace hardcoded `portfolio_config.py` with per-user DB storage
- [ ] Add portfolio management UI (add/edit/delete holdings)
- [ ] Row Level Security: users can only see their own data

### Phase 2: Credit System + AI Billing
- [ ] Credit balance table in Supabase
- [ ] Free credits on signup (amount per Q10)
- [ ] Credit deduction on each AI call
- [ ] "Buy Credits" UI (Stripe integration)
- [ ] Credit balance display in sidebar
- [ ] Rate limiting per user (not just global)

### Phase 3: Domain + Deployment
- [ ] Register mindmarket.ai (Porkbun/Namecheap)
- [ ] Set up Cloudflare DNS
- [ ] Deploy to Railway/Render
- [ ] Configure custom domain + SSL
- [ ] Set up email (contact@mindmarket.ai)
- [ ] Add Sentry error tracking

### Phase 4: Polish + Legal
- [ ] Landing page (hero, features, pricing, CTA)
- [ ] Terms of Service
- [ ] Privacy Policy
- [ ] Financial Disclaimer ("not investment advice")
- [ ] Contact/support page
- [ ] Logo + favicon
- [ ] SEO meta tags

### Phase 5: Growth Features
- [ ] Broker API integration (Robinhood/Moomoo auto-import)
- [ ] CSV portfolio upload
- [ ] Historical portfolio tracking (time-series P&L)
- [ ] Email alerts (margin warning, VaR breach)
- [ ] Mobile optimization
- [ ] Analytics (PostHog/Mixpanel)

---

## 8. Development Notes

### Running Locally
```bash
# Start Streamlit
streamlit run app.py

# Start Ollama (for local AI)
ollama serve
# In another terminal:
ollama run deepseek-r1:14b

# Run tests
python -m pytest tests/unit/ -x -q
```

### Key Session State Keys
| Key | Type | Set By | Used By |
|-----|------|--------|---------|
| `analysis_ready` | bool | app.py (after Run Analysis) | All pages (guard) |
| `report` | RiskReport | app.py | All pages |
| `weights` | dict | app.py | All pages |
| `prices` | DataFrame | app.py | Pages 1-4, 9 |
| `_portfolio_meta` | dict | shared_sidebar.py / app.py | Overview, Portfolio, Simulator |
| `_model_provider` | str | shared_sidebar.py | call_llm() |
| `_api_key_input` | str | shared_sidebar.py | call_llm() (Codex) |
| `_deepseek_key` | str | shared_sidebar.py | call_llm() (DeepSeek) |
| `_ollama_model` | str | shared_sidebar.py | call_llm() (Ollama) |
| `_ollama_reachable` | bool | shared_sidebar.py | Provider list filtering |
| `_llm_configured` | bool | shared_sidebar.py | UI status indicator |
| `_lang` | str | shared_sidebar.py | i18n across all pages |
| `smart_money_data` | list | pages/8_Institutions.py | AI institutional digest |

### Cost Basis / P&L Calculation
```
Total P&L = Net Equity - Cost Basis
Net Equity = Total Long (market value) - Margin Loan
```
Displayed in: sidebar, Overview page KPIs, Scenario Simulator.

### Provider Auto-Detection Logic
1. On first session load, probe `http://localhost:11434/api/tags` (1s timeout)
2. If reachable → show all 3 providers (Codex, DeepSeek, Ollama)
3. If unreachable → hide Ollama from dropdown, auto-switch to Codex
4. User can click 🔄 to re-probe after starting Ollama
