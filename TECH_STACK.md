# MindMarket AI - Technology Stack & Skills

> Portfolio Risk Management Platform | Quantitative Finance Application

---

## Project Overview

An institutional-grade portfolio risk analytics platform supporting 25+ equities and 6 crypto assets, with real-time risk calculation, AI-powered market intelligence, standalone ticker research, and bilingual UI.

**Scale**: ~30,000 lines of Python | 10+ external API integrations | 522 tests passing | 10 Streamlit pages

---

## 1. Quantitative Finance & Risk Analytics

| Skill | Implementation |
|-------|---------------|
| **Monte Carlo VaR/CVaR** | 5,000-50,000 path simulation for Value-at-Risk and Expected Shortfall (95th/99th percentile) |
| **EWMA Covariance** | Exponentially-weighted moving average (lambda=0.94) for dynamic correlation modeling |
| **Multi-Factor Beta Analysis** | OLS regression against SPY, QQQ, GLD, TLT, IWM, VTV with statistical significance (t-stats, p-values, R-squared) |
| **Efficient Frontier** | Markowitz portfolio optimization via `scipy.optimize.minimize` (min variance, max Sharpe) |
| **Stress Testing** | Scenario analysis with asset-level loss attribution, conditional multivariate normal propagation |
| **Drawdown Analysis** | Maximum drawdown, duration statistics, rolling drawdown series |
| **Component VaR** | Euler decomposition and risk attribution by asset |
| **Barra Attribution** | PCA factor extraction with benchmark-labeled factors |
| **Margin Call Detection** | Leverage monitoring, equity ratio, distance-to-call calculations |
| **DCF Valuation** | CAPM-based discount rate, multi-stage growth model |
| **Macro Sensitivity** | Beta exposure to interest rates, USD index, crude oil |
| **Liquidity Risk** | Days-to-liquidate based on 30-day average daily volume (ADV) |
| **Regime Detection** | HMM (Gaussian mixture EM), volatility ratio, SMA trend, composite voting |

---

## 2. Options Analytics

| Feature | Detail |
|---------|--------|
| Pricing | Black-Scholes analytical pricing with Newton-Raphson IV solver |
| Greeks | Delta, Gamma, Theta, Vega, Rho — per-contract and portfolio-level |
| Strategies | 10 types: long/short call/put, spreads, straddle, strangle, iron condor, collar |
| IV Surface | 3D implied volatility surface from live option chains |
| Flow Scanner | Unusual volume detection, large premium trades, put/call ratio signals |

---

## 3. Python Application Development

### UI - Streamlit
- Multi-page application architecture (10 pages)
- Session state management for cross-page data sharing
- Custom CSS injection for professional dark-mode UI
- Design system with centralized tokens (colors, typography, spacing)
- Responsive sidebar with real-time portfolio refresh, provider auto-detection
- Three-tier caching: Session State → `@st.cache_data` → file system

### Concurrency
- `ThreadPoolExecutor` for parallel data fetching (5 workers)
- `concurrent.futures.as_completed` for result aggregation

---

## 4. AI/LLM Integration

| Technology | Usage |
|-----------|-------|
| **Anthropic Claude API** | AI risk briefing, market sentiment, scenario narrative, ticker research summary |
| **DeepSeek API** (via OpenAI client) | Alternative LLM backend for cheap cloud inference |
| **Ollama** (local LLM) | Cost-effective local inference (deepseek-r1:14b), auto-detected via localhost probe |
| **Prompt Engineering** | System prompts, structured output, temperature tuning, token limits |
| **Multi-Provider Architecture** | Seamless fallback between Claude, DeepSeek, Ollama via `call_llm()` abstraction |
| **Per-Page AI Digests** | Dedicated narrative summaries on every page (risk, market, scenario, options, trading floor, institutional, quant, ticker) |

---

## 5. Data Engineering & ETL

| Component | Detail |
|-----------|--------|
| **Data Sources** | Yahoo Finance (yfinance), FMP API, RSS feeds (Reuters/CNBC/FT/Bloomberg), CNN Fear & Greed, SEC EDGAR |
| **Data Pipeline** | Robust ETL with per-ticker error isolation, 5-point data quality validation |
| **Caching** | Pickle-based file cache with configurable TTL (24h price / 6h volume) |
| **Data Validation** | Min data points (20+), missing rate (≤30%), negative price check, extreme return detection, suspension detection |
| **Data Cleaning** | Forward-fill, linear interpolation for small gaps, winsorization (1st-99th percentile) |

---

## 6. Data Visualization - Plotly

- Monte Carlo VaR distribution histograms
- Efficient frontier scatter plots
- Correlation heatmaps
- Component VaR bar charts
- Cumulative return line charts
- Risk attribution treemaps
- Scenario waterfall charts
- Custom styling: dark mode, transparent backgrounds, hover data

---

## 7. Reporting & Export

| Tool | Usage |
|------|-------|
| **FPDF2** | Multi-page enterprise PDF risk report with custom header/footer, chart embedding |
| **openpyxl** | Multi-sheet Excel export (Summary, Risk Metrics, Portfolio, Correlations, Stress Test) |
| **Kaleido** | Plotly chart → PNG static image export for PDF embedding |

---

## 8. Testing & Code Quality

| Tool | Usage |
|------|-------|
| **pytest** | 522 unit/integration/performance tests |
| **pytest-cov** | Code coverage measurement with HTML reports |
| **pytest-asyncio** | Async function testing |
| **Black** | Automatic code formatting (100 char line, Python 3.10) |
| **Ruff** | Fast linting (pycodestyle, pyflakes, isort, naming) |
| **MyPy** | Static type checking on core modules |
| **pre-commit** | Git hooks: black, ruff, trailing whitespace, YAML check, large file prevention |

---

## 9. DevOps & Infrastructure

| Component | Detail |
|-----------|--------|
| **Docker** | Python 3.10 slim image, Streamlit on port 8501 |
| **docker-compose** | Single-service app orchestration with env injection |
| **GitHub Actions CI/CD** | Automated test suite + code quality checks on push/PR |
| **Codecov** | Coverage tracking and PR reports |
| **Streamlit Cloud** | Current production deployment at mindmarketai.streamlit.app |

---

## 10. Logging & Observability

| Tool | Usage |
|------|-------|
| **structlog** | Structured JSON logging with context binding and processor chains |
| **python-json-logger** | Rotating file handler (10MB max, 5 backups) |
| **Custom logging_config** | Centralized multi-handler setup (console + JSON file) |

---

## 11. Error Handling & Resilience

- Centralized error categorization (JSON decode, connection, insufficient data, linear algebra, weight errors)
- User-friendly error messages with recovery suggestions
- `safe_operation()` decorator for graceful degradation
- Retry logic with exponential backoff for API calls
- Fallback LLM providers when primary unavailable
- Network fault tolerance: expired cache as fallback on download failure

---

## 12. Numerical Stability

- Log-space GMM E-step (regime_detector) to avoid underflow
- Zero-division guards across Sharpe / Sortino / MaxDD (backtest_engine)
- EWMA covariance edge cases, NaN safety (risk_engine)
- IV solver wider bracket + strike ordering guards (options_engine)
- Log-space cumulative returns (performance_attribution)

---

## 13. Internationalization (i18n)

- Custom dual-language system: Simplified Chinese + English
- 500+ translated strings (1,159 lines of i18n mapping)
- Language-aware UI rendering across all pages and components

---

## 14. External APIs Integrated

| API | Purpose |
|-----|---------|
| Yahoo Finance (yfinance) | Historical prices, fundamentals, news, volume |
| Anthropic Claude | AI narrative summaries on every page |
| DeepSeek | Alternative LLM inference |
| Financial Modeling Prep (FMP) | Earnings transcripts, price targets, insider trades, analyst consensus |
| SEC EDGAR | 13F institutional filings (31 top institutions) |
| CNN Fear & Greed | Market sentiment index |
| RSS Feeds | Reuters, CNBC, MarketWatch, FT, Bloomberg macro news |
| Ollama | Local LLM inference |

---

## 15. Design Patterns & Architecture

- **Factory Pattern**: `_build_engine()` for risk engine construction
- **Strategy Pattern**: Multiple LLM backends (Claude / DeepSeek / Ollama) unified via `call_llm()`
- **Provider Pattern**: DataProvider + CachedDataProvider abstraction
- **Decorator Pattern**: `@st.cache_data`, `@st.cache_resource`, `@safe_operation`
- **Template Method**: PDF report generation with custom header/footer
- **Separation of Concerns**: UI (pages/ui) / Domain Logic (risk_engine, options_engine, etc.) / Data Layer (data_provider) / Cross-cutting (logging, i18n, error handling)

---

## Key Technical Highlights

1. **Quantitative Finance**: VaR, Monte Carlo, EWMA, Markowitz optimization, multi-factor models, regime detection
2. **AI Integration**: Multi-provider LLM architecture with auto-detection, per-page narrative digests
3. **Data Engineering**: Robust ETL pipeline, multi-source aggregation, 3-tier caching
4. **Production-Ready**: Structured logging, error recovery, 522 tests, Docker deployment, CI/CD
5. **Software Engineering**: Design patterns, type safety (MyPy), linting (Ruff/Black), pre-commit hooks
6. **UX Polish**: Bilingual UI (500+ keys), dark theme, auto-detected local LLM, cost basis P&L tracking
