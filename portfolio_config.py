"""
portfolio_config.py
单一持仓来源 — 只需在这里更新股数，app 和 calc_weights 都会自动使用最新数据。
"""

PORTFOLIO_HOLDINGS = {
    'NVDA':  {'shares': 25.00},
    'GOOGL': {'shares': 12.41},
    'META':  {'shares': 6.31},
    'MSFT':  {'shares': 9.06},
    'TSLA':  {'shares': 8.00},
    'TSM':   {'shares': 5.39},
    'NFLX':  {'shares': 17.01},
    'AVGO':  {'shares': 4.31},
    'AXP':   {'shares': 5.00},
    'INTU':  {'shares': 3.00},
    'MU':    {'shares': 0.77},
    'SOFI':  {'shares': 45.00},
    'VST':   {'shares': 4.01},
    'COST':  {'shares': 0.55},
    'HOOD':  {'shares': 10.00},
    'ONDS':  {'shares': 30.00},
    'CPNG':  {'shares': 10.00},
    'SMMT':  {'shares': 15.00},
    'S':     {'shares': 13.00},
    'COPX':  {'shares': 5.00},
    'AA':    {'shares': 7.01},
    'TQQQ':  {'shares': 7.00},
    'QQQ':   {'shares': 2.16},
    'SPY':   {'shares': 1.97},
    'GLD':   {'shares': 2.53},
    # 加密货币
    'BTC-USD':  {'shares': 0.038},
    'ETH-USD':  {'shares': 0.60},
    'XRP-USD':  {'shares': 236},
    'ADA-USD':  {'shares': 1133},
    'SOL-USD':  {'shares': 2.5},
    'LINK-USD': {'shares': 16.00},
}

MARGIN_LOAN = 16772.11
