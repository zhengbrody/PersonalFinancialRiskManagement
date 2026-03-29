"""
根据持仓自动从 Yahoo Finance 获取当前价格，计算权重 JSON
运行方式: python calc_weights.py
"""

import json
import yfinance as yf

from portfolio_config import PORTFOLIO_HOLDINGS, MARGIN_LOAN

portfolio = PORTFOLIO_HOLDINGS
margin_loan = MARGIN_LOAN

print("正在获取当前价格...")
values = {}
for ticker, info in portfolio.items():
    try:
        hist = yf.Ticker(ticker).history(period='2d', auto_adjust=True)
        if hist.empty:
            print(f"  警告: {ticker} 无数据，跳过")
            continue
        price = float(hist['Close'].iloc[-1])
        values[ticker] = price * info['shares']
    except Exception as e:
        print(f"  警告: {ticker} 获取失败 ({e})，跳过")

total_long = sum(values.values())
net_equity = total_long - margin_loan

print(f"\n{'='*50}")
print(f"总持仓市值:  ${total_long:,.2f}")
print(f"保证金贷款:  ${margin_loan:,.2f}")
print(f"净资产:      ${net_equity:,.2f}")
print(f"杠杆率:      {total_long / net_equity:.2f}x")
print(f"{'='*50}")

weights = {k: round(v / total_long, 6) for k, v in values.items()}

print("\n各资产市值和权重:")
for ticker, val in sorted(values.items(), key=lambda x: -x[1]):
    print(f"  {ticker:<12} ${val:>8,.2f}  ({weights[ticker]:.2%})")

print("\n复制以下 JSON 到 app.py 侧边栏:")
print(json.dumps(weights, indent=2))
