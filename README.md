<div align="center">

# 📊 MindMarket AI

### Institutional-Grade Portfolio Risk Analytics · 机构级投资组合风险分析平台

[![Live Demo](https://img.shields.io/badge/🔴_LIVE-mindmarketai.streamlit.app-FF4B4B?style=for-the-badge)](https://mindmarketai.streamlit.app/)

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.30%2B-FF4B4B?style=flat-square&logo=streamlit&logoColor=white)](https://streamlit.io)
[![Claude](https://img.shields.io/badge/AI-Claude_%7C_DeepSeek_%7C_Ollama-blueviolet?style=flat-square&logo=anthropic)](https://anthropic.com)
[![CI](https://github.com/zhengbrody/PersonalFinancialRiskManagement/actions/workflows/ci.yml/badge.svg)](https://github.com/zhengbrody/PersonalFinancialRiskManagement/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](LICENSE)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white)]()

**[English](#english) · [中文](#中文)**

</div>

---

<a name="english"></a>

## ⚡ Overview

**MindMarket AI** is an institutional-grade portfolio risk analytics platform built on a production-quality quantitative stack — Monte Carlo VaR, multi-factor attribution, options Greeks, regime detection, SEC 13F tracking, and AI-powered narrative summaries — delivered through a clean 10-page Streamlit dashboard.

> Built to bridge professional hedge-fund analytics and retail-friendly UX.

---

## 📸 Screenshots

<div align="center">

![Landing Page](docs/screenshots/01_landing.png)
*Landing · feature grid · personas · tech badges*

![TradingView Page](docs/screenshots/02_tradingview.png)
*Page 5 — Embedded TradingView charts + technical analysis*

![Ticker Research Page](docs/screenshots/03_ticker_research.png)
*Page 10 — Standalone any-ticker deep dive with AI recommendation*

![Trading Floor Page](docs/screenshots/04_trading_floor.png)
*Page 7 — Bloomberg-style market monitor*

</div>

---

## 🎯 Core Capabilities

| Domain | Highlights |
|---|---|
| 🛡️ **Risk Engine** | Monte Carlo VaR/CVaR · EWMA covariance (λ=0.94) · Component VaR · Stress testing · Margin-call distance |
| 📈 **Factor Models** | 6-factor OLS with t-statistics · Macro sensitivities (rates/USD/oil) · Barra PCA attribution |
| 🎲 **Options Lab** | Black-Scholes + full Greeks · Newton-Raphson IV · 10 strategy builders · 3D IV surface |
| 🏛️ **Institutional Intel** | SEC 13F parser (top ~30 filers) · Smart-money overlap · Crowding detection · Unusual options flow |
| 🔄 **Regime & Backtest** | HMM (Gaussian mixture EM) · Vectorized backtesting · Brinson-Hood-Beebower attribution |
| 🤖 **AI Digests** | Narrative summaries on every page (Claude / DeepSeek / Ollama with auto-detection) |
| 🌏 **Bilingual UI** | 500+ labels across EN/中文 · dark-mode design system |

---

## 🌐 Live Demo

👉 **[mindmarketai.streamlit.app](https://mindmarketai.streamlit.app/)**

---

## 🗂️ Ten-Page Dashboard

| # | Page | What It Shows |
|---|------|---------------|
| 1 | 🏠 **Overview** | KPIs, cumulative returns, drawdown, cost-basis P&L, AI digest |
| 2 | 🛡️ **Risk** | VaR/CVaR, component VaR, factor betas, 3-mode stress testing, AI risk briefing |
| 3 | 📰 **Markets** | VIX · Fear & Greed · Yield curve · Macro news · AI sentiment (all holdings) · Earnings AI |
| 4 | 💼 **Portfolio** | Efficient frontier · Trade blotter · Scenario simulator (-30% ~ +30%) · Margin monitor |
| 5 | 📉 **TradingView** | Embedded TradingView charts + technical analysis |
| 6 | 🎲 **Options** | Strategy builder · Greeks · IV surface · Educational walkthroughs |
| 7 | 🏙️ **Trading Floor** | Bloomberg-style regime + sectors + movers + options flow |
| 8 | 🏛️ **Institutions** | SEC 13F smart money · Institution deep dive · Options flow intelligence |
| 9 | 🔬 **Quant Lab** | Backtesting · Performance attribution · Regime analysis |
| 10 | 🔎 **Ticker Research** | Standalone any-ticker deep dive (10 data sources + AI recommendation) |

---

## 🚀 Quick Start

### Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.10+ | Runtime |
| pip | latest | Package manager |
| Git | any | Clone repo |
| Anthropic API key | optional | Claude AI digests |
| FMP API key | optional | Earnings transcripts / price targets |
| Ollama | optional | Local LLM (auto-detected on port 11434) |

### Option 1 — Native Python

```bash
git clone https://github.com/zhengbrody/PersonalFinancialRiskManagement.git
cd PersonalFinancialRiskManagement
pip install -r requirements.txt
streamlit run app.py
# → http://localhost:8501
```

### Option 2 — Docker

```bash
docker-compose up --build
# → http://localhost:8501
```

### Option 3 — Streamlit Cloud (one-click)

Fork → connect to [share.streamlit.io](https://share.streamlit.io) → set secrets → deploy.

```toml
# .streamlit/secrets.toml
ANTHROPIC_API_KEY = "sk-ant-..."
DEEPSEEK_API_KEY  = "sk-..."
FMP_API_KEY       = "..."
```

---

## 🏗️ Architecture

```
                    ┌─────────────────────┐
                    │  portfolio_config   │  ← Holdings + cost basis
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │   data_provider     │  ← yfinance + caching + validation
                    └──────────┬──────────┘
                               │
                ┌──────────────▼──────────────┐
                │      risk_engine.py         │
                │   EWMA · MC VaR · OLS       │
                │   Stress · Frontier · Barra │
                └──────────────┬──────────────┘
                               │
      ┌────────┬────────┬──────┼──────┬────────┬────────┐
      ▼        ▼        ▼      ▼      ▼        ▼        ▼
  options  backtest  regime  vol.  inst.   options   perf.
  engine   engine   detector scan. track.  flow     attrib.
      └────────┴────────┴──────┼──────┴────────┴────────┘
                               │
                     ┌─────────▼─────────┐
                     │    app.py (UI)    │
                     │  10 Streamlit     │
                     │  pages + call_llm │
                     └───────────────────┘
```

---

## 🛠️ Tech Stack

| Layer | Tools |
|-------|-------|
| **UI** | Streamlit · Plotly · custom CSS (dark theme) |
| **Quant** | NumPy · pandas · SciPy (`optimize`, `stats`) |
| **Data** | yfinance · SEC EDGAR · FMP API · CNN Fear & Greed · RSS feeds |
| **AI** | Anthropic Claude · DeepSeek · Ollama (local) |
| **Testing** | pytest · pytest-cov · pytest-asyncio (unit · integration · performance) |
| **Quality** | black · ruff · mypy · pre-commit · GitHub Actions CI |
| **Logging** | structlog · python-json-logger |
| **Deploy** | Docker · docker-compose · Streamlit Cloud · **AWS (CDK Python, see below)** |

---

## ☁️ AWS Migration (Phases 1–2 complete)

The original Streamlit-only deployment is being migrated to a distributed AWS
architecture with infrastructure-as-code. **Status:** Phase 1 + Phase 2
designed, deployed end-to-end, smoke-tested, and torn back down. Live demo
URL is available on demand — `./infra/scripts/deploy-phase-1.sh` brings it
up in ~10 min.

### Target architecture

```
                       ┌────────────────────┐
       Users   ──────► │ CloudFront + WAF   │      (Phase 4)
                       └─────────┬──────────┘
                                 │
                       ┌─────────▼──────────┐
                       │  EC2 (Streamlit)   │      Phase 1
                       │  Caddy auto-HTTPS  │      + Let's Encrypt
                       │  CloudWatch Agent  │      via *.nip.io
                       └─────────┬──────────┘
                                 │ feature flag USE_REMOTE_COMPUTE
                                 │
                       ┌─────────▼──────────┐
                       │  REST API Gateway  │      Phase 2
                       │  api_key + 1k/day  │
                       └─────────┬──────────┘
                                 │
        ┌────────────────────────┼────────────────────────┐
        │                        │                        │
   ┌────▼─────┐            ┌─────▼─────┐            ┌────▼─────┐
   │ /var     │            │ /greeks   │            │ /price/* │
   │ Lambda   │            │ Lambda    │            │ Lambda   │
   │ MC VaR   │            │ BS+Greeks │            │ yfinance │
   │ 3GB mem  │            │ 512MB     │            │ +DDB rw  │
   └────┬─────┘            └───────────┘            └────┬─────┘
        │                                                │
        └──────────► DynamoDB PriceCache ◄───────────────┘
                     pk=TICKER#sym
                     sk=BAR#interval#period
                     TTL=expiresAt
```

### Cost (US East 1, on-demand teardown pattern)

| Stack | Idle | While running | Verified spend |
|---|---|---|---|
| Foundation (VPC + SG + S3 logs) | $0 | $0 | $0 |
| Compute (EC2 t3.micro + EIP) | $0 | ~$9.30/mo | < $0.50 across 3 deploys |
| Data (DynamoDB on-demand) | $0 | $0 (free tier) | $0 |
| Api (3 Lambdas + REST API + UsagePlan) | $0 | ~$3-5/mo at 50K req | < $0.20 across 3 deploys |
| CDKToolkit (one-time bootstrap) | ~$0.02/mo | ~$0.02/mo | $0.02 |

**Total verified Phase 1 + Phase 2 spend: ~$0.70 of $200 Free Plan credits.**
Strategy: deploy when demoing, destroy when not. Re-create takes ~10 min via
`deploy-phase-1.sh` and `cdk deploy MindMarket-Data MindMarket-Api`.

### Repo layout for the migration

```
infra/                              CDK Python (one-shot scaffold + 4 stacks)
├── infra/foundation_stack.py       VPC, SG, S3 logs (Phase 1)
├── infra/compute_stack.py          EC2 + EIP + IAM + user-data (Phase 1)
├── infra/data_stack.py             DynamoDB PriceCache (Phase 2)
├── infra/api_stack.py              REST API + 3 Lambdas + UsagePlan (Phase 2)
└── scripts/{deploy-phase-1.sh, destroy.sh}

libs/mindmarket_core/               Pure-compute primitives (no I/O)
├── constants.py · var.py · portfolio_math.py · black_scholes.py · data_prep.py

services/                           Lambda function bodies
├── risk-calculator/   handler.py + Dockerfile + tests/   POST /var
├── options-pricer/    handler.py + Dockerfile + tests/   POST /greeks
└── price-cache/       handler.py + Dockerfile + tests/   GET  /price/{ticker}

docs/adr/                           Architecture Decision Records
├── 0001-foundation-vpc-design.md   Why 2 AZs, 0 NAT, port 80 for ACME
└── 0002-phase2-compute-design.md   Why Container Image Lambda, REST not HTTP API
docs/aws/phase-1-ec2.md             Operational runbook + 6 troubleshooting recipes
docs/migration-log.md               Dated log of what shipped, by session
```

### Smoke-test results (verified during Phase 2 deploy)

| Endpoint | Input | Output | Latency |
|---|---|---|---|
| `POST /greeks` | ATM 1Y call S=K=100 r=5% σ=20% | **price 10.4506, delta 0.6368** (matches Hull 17.5 to 4 dp) | 156 ms warm |
| `POST /var` | 3-asset synthetic returns, 5K sims, 21d horizon | VaR95 6.12%, CVaR95 7.17% (CVaR ≥ VaR ✓) | 9 s cold, < 1 s warm |
| `GET /price/{t}` | AAPL 5d 1d | Architecture verified; yfinance 0.2.50 ↔ Yahoo API drift returns empty df | 21 s cold |

### What I Learned (real bugs found in real deploys)

| Bug | Root cause | Lesson |
|---|---|---|
| `GroupDescription` rejected with em-dash `—` | EC2 SecurityGroup props are ASCII-only | Lint passes don't catch service-level constraints — only real CFN does |
| `compose build requires buildx 0.17+` on AL2023 | Bundled buildx is 0.12; Compose v2.31 wants 0.17 | Always pin tooling versions in IaC; AMI bundles drift |
| `OCI runtime exec failed: curl: file not found` | `python:3.10-slim` doesn't include curl | Healthchecks should use base-image-native tools (`python -c urllib`) |
| `pip install` failed compiling NumPy from source in Lambda image | M-series Mac builds arm64; Lambda is x86_64; numpy 2.x lacks arm64 wheel | Always set `platform=LINUX_AMD64` on `DockerImageCode.from_image_asset` |
| `Runtime.ImportModuleError: No module named 'pandas'` | Eager `__init__.py` `from . import var` forced every consumer to install pandas | Lazy package init when sub-modules have divergent transitive deps |
| `JSONDecodeError` from yfinance for every ticker | Yahoo API contract drifted; yfinance 0.2.50 stale | External free data sources are fragile; production needs paid feed (FMP/Polygon) |

### Quick deploy / destroy

```bash
# One-time per AWS account/region
cd infra && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cdk bootstrap aws://<account>/<region> --profile mindmarket

# Deploy everything (~10 min)
export OPERATOR_IP=$(curl -s -4 ifconfig.me)
cdk deploy --all --profile mindmarket --context operator_ip=$OPERATOR_IP

# Smoke test (URL + key from outputs.json)
API_URL=$(jq -r '.["MindMarket-Api"].ApiUrl' cdk.out/outputs.json | sed 's:/$::')
KEY_ID=$(jq -r '.["MindMarket-Api"].ApiKeyId' cdk.out/outputs.json)
API_KEY=$(aws apigateway get-api-key --api-key $KEY_ID --include-value --profile mindmarket --query value --output text)
curl -X POST "$API_URL/greeks" -H "x-api-key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"spot":100,"strike":100,"time_to_expiry_years":1,"risk_free_rate":0.05,"volatility":0.2,"option_type":"call"}'

# Tear it all down (~3 min)
./infra/scripts/destroy.sh --force
```

Full operational details in `docs/aws/phase-1-ec2.md`.

---

## 🧪 Testing

```bash
# Full suite
python -m pytest tests/ -v

# No coverage (faster)
python -m pytest tests/ --no-cov

# Single module
python -m pytest tests/unit/test_risk_engine.py -v
```

Unit / integration / performance suites. Count the current suite with `python -m pytest tests/ --collect-only -q | tail -1`.

---

## 📂 Project Structure

```
MindMarket AI/
├── app.py                          # Entry · call_llm() · session state
├── risk_engine.py                  # Quant engine (EWMA, VaR, betas, stress)
├── data_provider.py                # Yahoo Finance with caching
├── market_intelligence.py          # News · DCF · insider · Reddit · crypto
├── options_engine.py               # Black-Scholes + Greeks + strategies
├── regime_detector.py              # HMM regime detection
├── institutional_tracker.py        # SEC 13F filing tracker
├── backtest_engine.py              # Vectorized strategy backtest
├── performance_attribution.py      # Brinson + factor attribution
├── volatility_scanner.py           # S&P movers · IV rank · sectors
├── options_flow.py                 # Unusual options activity
├── portfolio_config.py             # Holdings · margin · SECTOR_MAP (canonical)
├── i18n.py                         # Bilingual labels (500+ keys)
│
├── pages/                          # 10 Streamlit pages
│   └── 1_Overview.py ... 10_Ticker_Research.py
│
├── ui/                             # Design system
│   ├── tokens.py                   # Color / spacing / typography tokens
│   ├── components.py               # render_kpi_row · render_ai_digest · etc.
│   ├── shared_sidebar.py           # Provider detection · config
│   ├── floating_chat.py            # Persistent AI chat
│   └── tradingview.py              # TradingView widget integration
│
├── tests/                          # unit · integration · performance
│   ├── unit/ · integration/ · performance/
│
├── infra/                          # AWS CDK Python (Phase 1+2)
│   ├── infra/{foundation,compute,data,api}_stack.py
│   ├── scripts/{deploy-phase-1,destroy}.sh
│   └── app.py · cdk.json · requirements.txt
│
├── libs/mindmarket_core/           # Pure-compute library (no I/O, Lambda-importable)
│   └── constants · var · portfolio_math · black_scholes · data_prep
│
├── services/                       # Lambda functions (3)
│   ├── risk-calculator/  handler · Dockerfile · tests
│   ├── options-pricer/   handler · Dockerfile · tests
│   └── price-cache/      handler · Dockerfile · tests
│
├── docs/
│   ├── adr/                        # Architecture Decision Records (2)
│   ├── aws/phase-1-ec2.md          # AWS runbook + troubleshooting
│   ├── migration-log.md            # Dated session log
│   ├── user/                       # QUICK_START · SETUP · TROUBLESHOOT
│   └── archive/                    # Historical implementation notes
│
├── requirements.txt · requirements-dev.txt
├── Dockerfile · docker-compose.yml · compose.aws.yml · Caddyfile
├── pyproject.toml · pytest.ini · .pre-commit-config.yaml
└── .github/workflows/{ci.yml, deploy-services.yml}
```

---

## 🗺️ Roadmap

- [x] 10-page analytics dashboard
- [x] Multi-provider LLM integration with auto-detection
- [x] Scenario simulator + cost-basis P&L tracking
- [x] Standalone ticker research page
- [x] **AWS Phase 1** — VPC + EC2 + Caddy auto-HTTPS + CloudWatch (Apr 2026)
- [x] **AWS Phase 2** — REST API GW + 3 Lambda DockerImageFunctions + DynamoDB cache (Apr 2026)
- [ ] AWS Phase 3 — Cognito auth · async backtest pipeline · observability dashboards
- [ ] AWS Phase 4 — Cost optimization · 6-pager design doc · demo video
- [ ] Multi-user auth (Cognito or Supabase) + per-user portfolios
- [ ] Credit-based AI billing with Stripe
- [ ] Custom domain @ **mindmarket.ai**
- [ ] OAuth broker integration (Robinhood / Moomoo)
- [ ] Email alerts (margin warning, VaR breach)

---

## 📄 License

MIT. See [LICENSE](LICENSE).

---

<a name="中文"></a>

## ⚡ 项目概览

**MindMarket AI** 是一个机构级投资组合风险分析平台，基于专业量化栈构建——蒙特卡洛 VaR、多因子归因、期权希腊字母、市场状态识别、SEC 13F 跟踪、AI 叙述摘要——通过简洁的 10 页 Streamlit 仪表盘呈现。

> 目标：把对冲基金级分析能力与零售友好的 UX 连接起来。

---

## 🎯 核心能力

| 领域 | 亮点 |
|---|---|
| 🛡️ **风险引擎** | 蒙特卡洛 VaR/CVaR · EWMA 协方差（λ=0.94）· 边际 VaR · 压力测试 · 保证金追缴距离 |
| 📈 **因子模型** | 6 因子 OLS（带 t 统计量）· 宏观敏感度（利率/美元/原油）· Barra PCA 归因 |
| 🎲 **期权实验室** | Black-Scholes + 希腊字母 · Newton-Raphson IV · 10 种策略构建器 · 3D 隐波曲面 |
| 🏛️ **机构情报** | SEC 13F 解析器（约 30 家头部机构）· Smart money 重合 · 拥挤度检测 · 异常期权流 |
| 🔄 **状态识别 & 回测** | HMM（高斯混合 EM）· 向量化回测 · Brinson-Hood-Beebower 归因 |
| 🤖 **AI 摘要** | 每页独立的 AI 叙述（Claude / DeepSeek / Ollama 自动检测） |
| 🌏 **双语 UI** | 500+ 标签覆盖英文/中文 · 暗色主题设计系统 |

---

## ☁️ AWS 迁移(Phase 1+2 完成)

原 Streamlit-only 部署正在迁往分布式 AWS 架构,IaC 全程 CDK。
**当前状态**:Phase 1 + Phase 2 设计、部署、烟测、销毁回环已全部跑通,
零残留。`./infra/scripts/deploy-phase-1.sh` ~10 分钟即可重建 demo URL。

| 阶段 | 内容 | 月成本(运行中)|
|---|---|---|
| Phase 1 | EC2 + Caddy auto-HTTPS + CloudWatch | ~$9.30 |
| Phase 2 | REST API + 3 Lambda + DynamoDB cache | ~$3-5 |
| 空闲(已 destroy) | CDKToolkit + S3 logs | ~$0.02 |

**真实部署验证**:`POST /greeks` 返回 ATM 1Y call 价格 10.4506(与 Hull 教材完全吻合,4 位小数),
`POST /var` 返回 VaR95 6.12% / CVaR95 7.17%(CVaR ≥ VaR ✓)。
完整运维 cookbook 在 [`docs/aws/operations.md`](docs/aws/operations.md)。

---

## 🚀 快速开始

### 前置要求

| 工具 | 版本 | 用途 |
|------|------|------|
| Python | 3.10+ | 运行时 |
| pip | 最新 | 包管理器 |
| Git | 任意 | 克隆仓库 |
| Anthropic API 密钥 | 可选 | Claude AI 摘要 |
| FMP API 密钥 | 可选 | 财报电话会 / 目标价 |
| Ollama | 可选 | 本地 LLM（自动检测 11434 端口）|

### 方式一 — 本地 Python

```bash
git clone https://github.com/zhengbrody/PersonalFinancialRiskManagement.git
cd PersonalFinancialRiskManagement
pip install -r requirements.txt
streamlit run app.py
# → http://localhost:8501
```

### 方式二 — Docker

```bash
docker-compose up --build
# → http://localhost:8501
```

### 方式三 — Streamlit Cloud（一键部署）

Fork → 连接到 [share.streamlit.io](https://share.streamlit.io) → 配置 secrets → 部署。

---

## 🧪 测试

```bash
python -m pytest tests/ -v
```

覆盖单元 / 集成 / 性能测试套件。使用 `python -m pytest tests/ --collect-only -q | tail -1` 查询当前测试数量。

---

## 🗺️ 路线图

- [x] 10 页分析仪表盘
- [x] 多后端 LLM 集成 + 自动检测
- [x] 情景模拟器 + 成本基础 P&L 跟踪
- [x] 独立股票研究页面
- [ ] 多用户登录系统（Supabase）
- [ ] 基于积分的 AI 计费（Stripe）
- [ ] 自定义域名 **mindmarket.ai**
- [ ] 券商 OAuth 接入（Robinhood / Moomoo）
- [ ] 邮件提醒（保证金、VaR 突破）

---

<div align="center">

**🔗 [mindmarketai.streamlit.app](https://mindmarketai.streamlit.app/)**

Built with ❤️ by [Zheng Dong](https://github.com/zhengbrody)

_If this project helps, consider leaving a ⭐ — it means a lot._

</div>
