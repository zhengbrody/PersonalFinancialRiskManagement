# 📊 Personal Financial Risk Management System

A full-stack portfolio risk dashboard built with Python + Streamlit. Supports bilingual UI (中文/English), live price fetching, Monte Carlo simulation, stress testing, AI chat analysis (Claude API or free local Ollama), and Excel export.

> **Live repo:** [github.com/zhengbrody/PersonalFinancialRiskManagement](https://github.com/zhengbrody/PersonalFinancialRiskManagement)

---

## Features

| Module | Description |
|--------|-------------|
| **Live Portfolio Loader** | One-click fetch from Yahoo Finance using your actual share counts |
| **Risk Engine** | Annual return, volatility, Sharpe ratio, max drawdown, VaR/CVaR (Monte Carlo), Beta vs SPY |
| **9 Analysis Tabs** | Cumulative returns, drawdown analysis, correlation heatmap, Monte Carlo distribution, stress test, risk attribution, rolling correlation, historical scenarios, cash deployment simulator |
| **Risk Attribution** | Euler component VaR decomposition — which asset is consuming your risk budget |
| **Sector Concentration** | Pie chart + table showing industry exposure |
| **Rolling Correlation** | 60-day rolling correlation vs portfolio — verify if hedges actually work |
| **Historical Scenarios** | COVID crash, 2022 bear market, 2018 Q4, 2008 crisis, crypto winter |
| **Cash Deployment Simulator** | Model adding cash reserves → Before/After risk metric comparison |
| **AI Chat Agent** | Claude API (cloud) or Ollama (free, fully local — DeepSeek-R1, Qwen, LLaMA) |
| **Excel Export** | 7-sheet report: Summary, Asset Details, Correlation, Covariance, Drawdown, Monte Carlo, Price History |
| **Bilingual UI** | Full 中文/English toggle, all labels translated |

---

## Screenshots

> *(Add screenshots here after first run)*

---

## Project Structure

```
.
├── app.py                # Streamlit frontend — all UI/UX
├── risk_engine.py        # Core risk calculations (VaR, CVaR, Beta, drawdown, etc.)
├── data_provider.py      # Yahoo Finance data fetching & preprocessing
├── portfolio_config.py   # ← Edit this to update your holdings
├── calc_weights.py       # CLI tool: fetch live prices → print weights JSON
├── i18n.py               # Bilingual string dictionary (中文/English)
├── requirements.txt      # Python dependencies
└── README.md
```

---

## Quick Start

### 1. Clone & install

```bash
git clone https://github.com/zhengbrody/PersonalFinancialRiskManagement.git
cd PersonalFinancialRiskManagement

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

### 2. Configure your portfolio

Edit `portfolio_config.py` — update the `shares` for each position:

```python
PORTFOLIO_HOLDINGS = {
    'NVDA':    {'shares': 25.00},
    'BTC-USD': {'shares': 0.038},
    # ... add/remove tickers as needed
}
MARGIN_LOAN = 16772.11   # set to 0 if no margin
```

### 3. Run the app

```bash
streamlit run app.py
```

Browser opens at `http://localhost:8501`.

### 4. Load your portfolio

Click **📡 Load My Portfolio (live prices)** in the sidebar → weights are calculated automatically.

---

## AI Chat Setup

### Option A — Claude API (cloud, best quality)

1. Get an API key at [console.anthropic.com](https://console.anthropic.com)
2. Enter it in the sidebar under **Chat Agent Settings**, or set the environment variable:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

### Option B — Ollama (free, fully local, no API key needed)

```bash
# Install Ollama
brew install ollama                  # macOS
# or download from https://ollama.com

# Pull a model (choose one)
ollama pull deepseek-r1:14b          # Best reasoning, ~9 GB
ollama pull qwen2.5:7b               # Fast, great Chinese support, ~4.7 GB
ollama pull llama3.1                 # Strong English, ~4.7 GB

# Start the server (keep this terminal open)
ollama serve
```

Then in the app sidebar: select **Ollama** as backend and enter the model name.

> DeepSeek-R1's reasoning chain (`<think>...</think>`) is automatically parsed — the thinking process is shown in a collapsible expander, and only the final answer is displayed in the chat.

---

## Workflow

```
portfolio_config.py   ← only file you need to edit for holdings changes
        │
        ├── calc_weights.py    (CLI: prints weights JSON for reference)
        │
        └── app.py             (Streamlit: loads live prices automatically)
                │
                ├── data_provider.py   (downloads & caches price history)
                └── risk_engine.py     (all risk calculations)
```

---

## Risk Metrics Reference

| Metric | Description |
|--------|-------------|
| **VaR 95%** | Value at Risk — max loss not exceeded in 95% of scenarios over the MC horizon |
| **CVaR 95%** | Conditional VaR — average loss in the worst 5% of scenarios |
| **Sharpe Ratio** | Risk-adjusted return `(R - Rf) / σ`, using 4.5% risk-free rate |
| **Max Drawdown** | Largest peak-to-trough decline in the historical period |
| **Beta** | Sensitivity to SPY (S&P 500). Beta > 1 = more volatile than market |
| **Component VaR %** | Euler decomposition: each asset's % contribution to total portfolio variance |
| **Rolling Correlation** | 60-day rolling Pearson correlation vs portfolio — lower = better diversifier |

---

## Dependencies

```
streamlit>=1.30
yfinance>=0.2.30
plotly>=5.18
pandas>=2.0
numpy>=1.24
anthropic>=0.40
openpyxl>=3.1
requests>=2.31    # for Ollama HTTP calls
```

---

## Notes

- **Crypto tickers** use Yahoo Finance format: `BTC-USD`, `ETH-USD`, `SOL-USD`, etc.
- **Margin loan** is factored into net equity and leverage display, but portfolio weights are calculated on gross market value (total long)
- **Historical scenarios** require a separate data download (~20–30s) and are triggered on-demand
- Price data is cached within the session — the Cash Deployment simulator reuses cached data without re-downloading

---

## License

MIT
