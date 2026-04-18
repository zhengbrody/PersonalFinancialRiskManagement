"""
ui/tradingview.py
TradingView widget embedding + tradingview-ta data integration.
"""

import streamlit as st
import streamlit.components.v1 as components
from typing import List, Optional, Dict
from tradingview_ta import TA_Handler, Interval


# ══════════════════════════════════════════════════════════════
#  1. Embeddable TradingView Widgets (Real-Time Charts)
# ══════════════════════════════════════════════════════════════

def render_advanced_chart(
    symbol: str,
    exchange: str = "NASDAQ",
    height: int = 700,
    interval: str = "D",
    theme: str = "dark",
    studies: Optional[List[str]] = None,
):
    """Render a TradingView Advanced Chart widget for a single ticker.
    If user is logged into TradingView in their browser, their saved layouts/indicators will load.
    """
    if studies is None:
        studies = ["MASimple@tv-basicstudies", "RSI@tv-basicstudies", "MACD@tv-basicstudies"]

    studies_json = str(studies).replace("'", '"')
    tv_symbol = f"{exchange}:{symbol}" if not any(c in symbol for c in [":"]) else symbol

    html = f"""
    <div class="tradingview-widget-container" style="height:{height}px;width:100%">
      <div id="tv_chart_{symbol}" style="height:100%;width:100%"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
      <script type="text/javascript">
        new TradingView.widget({{
          "autosize": true,
          "symbol": "{tv_symbol}",
          "interval": "{interval}",
          "timezone": "America/New_York",
          "theme": "{theme}",
          "style": "1",
          "locale": "en",
          "toolbar_bg": "#0F1117",
          "enable_publishing": false,
          "allow_symbol_change": true,
          "hide_top_toolbar": false,
          "hide_legend": false,
          "hide_side_toolbar": false,
          "save_image": true,
          "withdateranges": true,
          "details": true,
          "hotlist": true,
          "calendar": true,
          "studies": {studies_json},
          "container_id": "tv_chart_{symbol}",
          "backgroundColor": "rgba(15, 17, 23, 1)",
          "gridColor": "rgba(139, 148, 158, 0.06)"
        }});
      </script>
    </div>
    """
    components.html(html, height=height + 10, scrolling=False)


def render_fullpage_tradingview_with_watchlist(
    symbol: str = "NASDAQ:NVDA",
    height: int = 800,
    watchlist: Optional[List[str]] = None,
):
    """Full-featured chart with dynamic watchlist from user's portfolio."""
    import json as _json
    default_watchlist = [
        "NASDAQ:NVDA", "NASDAQ:GOOGL", "NASDAQ:META", "NASDAQ:TSLA",
        "NASDAQ:MSFT", "NYSE:TSM", "BITSTAMP:BTCUSD", "BITSTAMP:ETHUSD",
    ]
    wl = watchlist if watchlist else default_watchlist
    wl_json = _json.dumps(wl)

    html = f"""
    <div class="tradingview-widget-container" style="width:100%;height:{height}px">
      <div id="tv_fullchart_wl" style="width:100%;height:100%"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
      <script type="text/javascript">
        new TradingView.widget({{
          "autosize": true,
          "symbol": "{symbol}",
          "interval": "D",
          "timezone": "America/New_York",
          "theme": "dark",
          "style": "1",
          "locale": "en",
          "enable_publishing": false,
          "allow_symbol_change": true,
          "hide_top_toolbar": false,
          "hide_legend": false,
          "hide_side_toolbar": false,
          "save_image": true,
          "withdateranges": true,
          "details": true,
          "hotlist": true,
          "calendar": true,
          "show_popup_button": true,
          "popup_width": "1000",
          "popup_height": "650",
          "watchlist": {wl_json},
          "studies": ["MASimple@tv-basicstudies","RSI@tv-basicstudies","MACD@tv-basicstudies","BB@tv-basicstudies"],
          "container_id": "tv_fullchart_wl",
          "backgroundColor": "rgba(15, 17, 23, 1)",
          "gridColor": "rgba(139, 148, 158, 0.06)"
        }});
      </script>
    </div>
    """
    components.html(html, height=height + 5, scrolling=False)


def render_fullpage_tradingview(symbol: str = "NASDAQ:NVDA", height: int = 800):
    """Render TradingView full-featured chart via official widget API.
    Includes: drawing tools, indicators, watchlist, details, calendar.
    If user is logged into TradingView in the same browser, their saved
    layouts and indicators will be available within the widget.
    """
    html = f"""
    <div class="tradingview-widget-container" style="width:100%;height:{height}px">
      <div id="tv_fullchart" style="width:100%;height:100%"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
      <script type="text/javascript">
        new TradingView.widget({{
          "autosize": true,
          "symbol": "{symbol}",
          "interval": "D",
          "timezone": "America/New_York",
          "theme": "dark",
          "style": "1",
          "locale": "en",
          "enable_publishing": false,
          "allow_symbol_change": true,
          "hide_top_toolbar": false,
          "hide_legend": false,
          "hide_side_toolbar": false,
          "save_image": true,
          "withdateranges": true,
          "details": true,
          "hotlist": true,
          "calendar": true,
          "show_popup_button": true,
          "popup_width": "1000",
          "popup_height": "650",
          "watchlist": ["NASDAQ:NVDA","NASDAQ:GOOGL","NASDAQ:META","NASDAQ:TSLA","NASDAQ:MSFT","NYSE:TSM","BITSTAMP:BTCUSD","BITSTAMP:ETHUSD"],
          "studies": ["MASimple@tv-basicstudies","RSI@tv-basicstudies","MACD@tv-basicstudies","BB@tv-basicstudies"],
          "container_id": "tv_fullchart",
          "backgroundColor": "rgba(15, 17, 23, 1)",
          "gridColor": "rgba(139, 148, 158, 0.06)"
        }});
      </script>
    </div>
    """
    components.html(html, height=height + 5, scrolling=False)


def render_mini_chart(symbol: str, exchange: str = "NASDAQ", height: int = 220):
    """Render a compact TradingView Mini Chart widget (auto full-width)."""
    tv_symbol = f"{exchange}:{symbol}" if ":" not in symbol else symbol
    html = f"""
    <div class="tradingview-widget-container" style="width:100%">
      <div class="tradingview-widget-container__widget"></div>
      <script type="text/javascript"
        src="https://s3.tradingview.com/external-embedding/embed-widget-mini-symbol-overview.js"
        async>
        {{
          "symbol": "{tv_symbol}",
          "width": "100%",
          "height": {height},
          "locale": "en",
          "dateRange": "3M",
          "colorTheme": "dark",
          "isTransparent": true,
          "autosize": true,
          "largeChartUrl": ""
        }}
      </script>
    </div>
    """
    components.html(html, height=height + 5)


def render_technical_analysis_widget(symbol: str, exchange: str = "NASDAQ", height: int = 500):
    """Render TradingView's built-in Technical Analysis gauge widget."""
    tv_symbol = f"{exchange}:{symbol}" if ":" not in symbol else symbol
    html = f"""
    <div class="tradingview-widget-container" style="width:100%">
      <div class="tradingview-widget-container__widget"></div>
      <script type="text/javascript"
        src="https://s3.tradingview.com/external-embedding/embed-widget-technical-analysis.js"
        async>
        {{
          "interval": "1D",
          "width": "100%",
          "isTransparent": true,
          "height": {height},
          "symbol": "{tv_symbol}",
          "showIntervalTabs": true,
          "displayMode": "single",
          "locale": "en",
          "colorTheme": "dark"
        }}
      </script>
    </div>
    """
    components.html(html, height=height + 5)


def render_screener_widget(height: int = 550, default_screen: str = "most_capitalized"):
    """Render TradingView Stock Screener widget."""
    html = f"""
    <div class="tradingview-widget-container">
      <div class="tradingview-widget-container__widget"></div>
      <script type="text/javascript"
        src="https://s3.tradingview.com/external-embedding/embed-widget-screener.js"
        async>
        {{
          "width": "100%",
          "height": {height},
          "defaultColumn": "overview",
          "defaultScreen": "{default_screen}",
          "market": "america",
          "showToolbar": true,
          "colorTheme": "dark",
          "locale": "en",
          "isTransparent": true
        }}
      </script>
    </div>
    """
    components.html(html, height=height + 10)


def render_ticker_tape(symbols: Optional[List[str]] = None):
    """Render a scrolling ticker tape at the top of the page."""
    if symbols is None:
        symbols = [
            {"proName": "NASDAQ:NVDA", "title": "NVDA"},
            {"proName": "NASDAQ:GOOGL", "title": "GOOGL"},
            {"proName": "NASDAQ:META", "title": "META"},
            {"proName": "NASDAQ:TSLA", "title": "TSLA"},
            {"proName": "NASDAQ:MSFT", "title": "MSFT"},
            {"proName": "BITSTAMP:BTCUSD", "title": "BTC"},
            {"proName": "BITSTAMP:ETHUSD", "title": "ETH"},
        ]
    else:
        symbols = [{"proName": s, "title": s.split(":")[-1]} for s in symbols]

    import json
    symbols_json = json.dumps(symbols)
    html = f"""
    <div class="tradingview-widget-container">
      <div class="tradingview-widget-container__widget"></div>
      <script type="text/javascript"
        src="https://s3.tradingview.com/external-embedding/embed-widget-ticker-tape.js"
        async>
        {{
          "symbols": {symbols_json},
          "showSymbolLogo": true,
          "isTransparent": true,
          "displayMode": "adaptive",
          "colorTheme": "dark",
          "locale": "en"
        }}
      </script>
    </div>
    """
    components.html(html, height=78)


def render_heatmap(height: int = 500):
    """Render TradingView stock heatmap (S&P 500)."""
    html = f"""
    <div class="tradingview-widget-container">
      <div class="tradingview-widget-container__widget"></div>
      <script type="text/javascript"
        src="https://s3.tradingview.com/external-embedding/embed-widget-stock-heatmap.js"
        async>
        {{
          "exchanges": [],
          "dataSource": "SPX500",
          "grouping": "sector",
          "blockSize": "market_cap_basic",
          "blockColor": "change",
          "locale": "en",
          "symbolUrl": "",
          "colorTheme": "dark",
          "hasTopBar": true,
          "isDataSetEnabled": true,
          "isZoomEnabled": true,
          "hasSymbolTooltip": true,
          "isMonoSize": false,
          "width": "100%",
          "height": {height}
        }}
      </script>
    </div>
    """
    components.html(html, height=height + 10)


# ══════════════════════════════════════════════════════════════
#  2. Technical Analysis Data (tradingview-ta)
# ══════════════════════════════════════════════════════════════

# Ticker → (exchange, screener) mapping
EXCHANGE_MAP = {
    # US Stocks
    "NVDA": ("NASDAQ", "america"), "GOOGL": ("NASDAQ", "america"),
    "META": ("NASDAQ", "america"), "MSFT": ("NASDAQ", "america"),
    "TSLA": ("NASDAQ", "america"), "NFLX": ("NASDAQ", "america"),
    "AVGO": ("NASDAQ", "america"), "INTU": ("NASDAQ", "america"),
    "MU": ("NASDAQ", "america"), "SOFI": ("NASDAQ", "america"),
    "HOOD": ("NASDAQ", "america"), "ONDS": ("NASDAQ", "america"),
    "CPNG": ("NYSE", "america"), "SMMT": ("NASDAQ", "america"),
    "S": ("NYSE", "america"), "COST": ("NASDAQ", "america"),
    "QQQ": ("NASDAQ", "america"), "SPY": ("AMEX", "america"),
    "GLD": ("AMEX", "america"), "COPX": ("AMEX", "america"),
    "AA": ("NYSE", "america"), "AXP": ("NYSE", "america"),
    "VST": ("NYSE", "america"), "TSM": ("NYSE", "america"),
    # Crypto
    "BTC-USD": ("BITSTAMP", "crypto"), "ETH-USD": ("BITSTAMP", "crypto"),
    "XRP-USD": ("BITSTAMP", "crypto"), "ADA-USD": ("BITSTAMP", "crypto"),
    "SOL-USD": ("BITSTAMP", "crypto"), "LINK-USD": ("BITSTAMP", "crypto"),
}

# Crypto ticker normalization (yfinance → TradingView)
_CRYPTO_TV = {
    "BTC-USD": "BTCUSD", "ETH-USD": "ETHUSD", "XRP-USD": "XRPUSD",
    "ADA-USD": "ADAUSD", "SOL-USD": "SOLUSD", "LINK-USD": "LINKUSD",
}


def get_ta_summary(ticker: str, interval: str = "1d") -> Optional[Dict]:
    """
    Fetch TradingView technical analysis summary for a ticker.

    Returns dict with:
      - recommendation: "BUY" | "SELL" | "NEUTRAL" | "STRONG_BUY" | "STRONG_SELL"
      - buy / sell / neutral counts
      - oscillators / moving_averages summaries
      - key indicators (RSI, MACD, etc.)
    """
    interval_map = {
        "1m": Interval.INTERVAL_1_MINUTE,
        "5m": Interval.INTERVAL_5_MINUTES,
        "15m": Interval.INTERVAL_15_MINUTES,
        "1h": Interval.INTERVAL_1_HOUR,
        "4h": Interval.INTERVAL_4_HOURS,
        "1d": Interval.INTERVAL_1_DAY,
        "1w": Interval.INTERVAL_1_WEEK,
        "1M": Interval.INTERVAL_1_MONTH,
    }

    tv_interval = interval_map.get(interval, Interval.INTERVAL_1_DAY)
    exchange, screener = EXCHANGE_MAP.get(ticker, ("NASDAQ", "america"))
    tv_ticker = _CRYPTO_TV.get(ticker, ticker)

    try:
        handler = TA_Handler(
            symbol=tv_ticker,
            screener=screener,
            exchange=exchange,
            interval=tv_interval,
        )
        analysis = handler.get_analysis()

        return {
            "ticker": ticker,
            "recommendation": analysis.summary["RECOMMENDATION"],
            "buy": analysis.summary["BUY"],
            "sell": analysis.summary["SELL"],
            "neutral": analysis.summary["NEUTRAL"],
            "oscillators": analysis.oscillators["RECOMMENDATION"],
            "moving_averages": analysis.moving_averages["RECOMMENDATION"],
            "indicators": {
                "RSI": round(analysis.indicators.get("RSI") or 0, 2),
                "MACD": round(analysis.indicators.get("MACD.macd") or 0, 4),
                "MACD_signal": round(analysis.indicators.get("MACD.signal") or 0, 4),
                "EMA_20": round(analysis.indicators.get("EMA20") or 0, 2),
                "SMA_50": round(analysis.indicators.get("SMA50") or 0, 2),
                "SMA_200": round(analysis.indicators.get("SMA200") or 0, 2),
                "BB_upper": round(analysis.indicators.get("BB.upper") or 0, 2),
                "BB_lower": round(analysis.indicators.get("BB.lower") or 0, 2),
                "ATR": round(analysis.indicators.get("ATR") or 0, 2),
                "ADX": round(analysis.indicators.get("ADX") or 0, 2),
                "Stoch_K": round(analysis.indicators.get("Stoch.K") or 0, 2),
                "CCI": round(analysis.indicators.get("CCI20") or 0, 2),
                "close": round(analysis.indicators.get("close") or 0, 2),
            },
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def get_portfolio_ta(tickers: List[str], interval: str = "1d") -> List[Dict]:
    """Fetch TA summaries for all portfolio tickers."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(get_ta_summary, tk, interval): tk for tk in tickers}
        for future in as_completed(futures):
            result = future.result()
            if result:
                results.append(result)
    return sorted(results, key=lambda x: tickers.index(x["ticker"]) if x["ticker"] in tickers else 999)


def get_tv_symbol(ticker: str) -> str:
    """Convert a yfinance ticker to TradingView symbol format (EXCHANGE:SYMBOL)."""
    exchange, _ = EXCHANGE_MAP.get(ticker, ("NASDAQ", "america"))
    tv_ticker = _CRYPTO_TV.get(ticker, ticker)
    return f"{exchange}:{tv_ticker}"
