"""
portfolio_config.py
单一持仓来源 — 只需在这里更新股数，app 和 calc_weights 都会自动使用最新数据。
"""

PORTFOLIO_HOLDINGS = {
    'NVDA':  {'shares': 25.00},
    'GOOGL': {'shares': 12.41},
    'META':  {'shares': 6.46},
    'MSFT':  {'shares': 9.19},
    'TSLA':  {'shares': 9.00},
    'TSM':   {'shares': 5.39},
    'NFLX':  {'shares': 17.01},
    'AVGO':  {'shares': 4.02},
    'AXP':   {'shares': 5.00},
    'INTU':  {'shares': 3.00},
    'MU':    {'shares': 0.77},
    'SOFI':  {'shares': 45.00},
    'VST':   {'shares': 4.01},
    'COST':  {'shares': 0.55},
    'HOOD':  {'shares': 10.00},
    'ONDS':  {'shares': 30.00},
    'COPX':  {'shares': 5.00},
    'AA':    {'shares': 7.01},
    'QQQ':   {'shares': 2.24},
    'SPY':   {'shares': 2.03},
    'GLD':   {'shares': 2.53},
    'SQQQ':  {'shares': 13.00},
    'SOXS':  {'shares': 10.00},
    'SPXS':  {'shares': 5.00},

    # 加密货币
    'BTC-USD':  {'shares': 0.038},
    'ETH-USD':  {'shares': 0.60},
    'XRP-USD':  {'shares': 236},
    'ADA-USD':  {'shares': 1133},
    'SOL-USD':  {'shares': 2.5},
    'LINK-USD': {'shares': 16.00},
}

MARGIN_LOAN = 16822

# 本金（总投入成本），可随时修改
TOTAL_COST_BASIS = 19700


# Canonical sector classification used across app.py, performance_attribution.py,
# and any page that needs sector breakdowns. Single source of truth.
SECTOR_MAP = {
    "NVDA": "Semiconductors", "AVGO": "Semiconductors", "TSM": "Semiconductors",
    "MU": "Semiconductors", "INTC": "Semiconductors", "AMD": "Semiconductors",
    "QCOM": "Semiconductors", "TXN": "Semiconductors",
    "GOOGL": "Big Tech", "GOOG": "Big Tech", "MSFT": "Big Tech",
    "META": "Big Tech", "AAPL": "Big Tech", "AMZN": "Big Tech",
    "INTU": "Software", "CRM": "Software", "SNOW": "Software", "NOW": "Software",
    "TSLA": "EV / Auto", "CPNG": "E-commerce", "BABA": "E-commerce",
    "NFLX": "Streaming / Media", "DIS": "Streaming / Media",
    "AXP": "Financials", "JPM": "Financials", "GS": "Financials",
    "SOFI": "Fintech", "HOOD": "Fintech", "PYPL": "Fintech", "SQ": "Fintech",
    "S": "Cybersecurity", "CRWD": "Cybersecurity", "PANW": "Cybersecurity",
    "SMMT": "Biotech", "ONDS": "Technology / IoT",
    "AA": "Materials", "COPX": "Mining ETF", "VST": "Utilities",
    "COST": "Consumer Staples", "WMT": "Consumer Staples",
    # Long-leverage / broad ETFs
    "TQQQ": "Leveraged ETF", "QQQ": "Tech ETF",
    "SPY": "Broad Market ETF", "GLD": "Gold / Commodities", "SLV": "Gold / Commodities",
    # Inverse/short ETFs (3x daily short — hedge instruments)
    "SQQQ": "Inverse ETF (3x QQQ)",
    "SOXS": "Inverse ETF (3x Semis)",
    "SPXS": "Inverse ETF (3x S&P)",
    # Crypto
    "BTC-USD": "Crypto", "ETH-USD": "Crypto", "XRP-USD": "Crypto",
    "ADA-USD": "Crypto", "SOL-USD": "Crypto", "LINK-USD": "Crypto",
    "DOGE-USD": "Crypto", "BNB-USD": "Crypto",
}
