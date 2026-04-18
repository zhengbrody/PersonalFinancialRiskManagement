"""
market_intelligence.py
市场情报模块 v2.0
──────────────────────────────────────────────────────────
功能：
  1. 国际宏观新闻聚合（RSS + yfinance）
  2. 持仓股票基本面数据（P/E、市值、EPS、股息率等）
  3. VIX 恐慌指数 & 收益率曲线
  4. AI 综合风险简报生成
  5. CNN Fear & Greed Index
  6. Insider Trading + Technical Signals
  7. Reddit 散户情绪 (Apify)
  8. FMP 财报电话会议逐字稿 + Claude 深度分析
"""

import logging
import numpy as np
import pandas as pd
import yfinance as yf
import requests
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
#  1. 国际宏观新闻聚合
# ══════════════════════════════════════════════════════════════

# RSS 源列表：覆盖美联储、全球宏观、地缘政治
MACRO_RSS_FEEDS = {
    "Reuters Business":    "https://www.rss.app/feeds/v1.1/tgSjPfjTQYNME2cZ.json",
    "CNBC Economy":        "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258",
    "MarketWatch":         "https://feeds.marketwatch.com/marketwatch/topstories/",
    "FT Markets":          "https://www.ft.com/rss/home",
    "Bloomberg Markets":   "https://feeds.bloomberg.com/markets/news.rss",
}


def _fetch_single_rss(source_name: str, url: str, per_source_limit: int, timeout: int) -> List[Dict]:
    """Fetch a single RSS feed. Called concurrently by fetch_macro_news_rss."""
    items_out = []
    try:
        resp = requests.get(url, timeout=timeout, headers={
            "User-Agent": "Mozilla/5.0 (compatible; PortfolioRisk/1.0)"
        })
        if resp.status_code != 200:
            return items_out

        content_type = resp.headers.get("Content-Type", "")

        # JSON feed (rss.app 格式)
        if "json" in url or "json" in content_type:
            data = resp.json()
            items = data.get("items", [])
            for item in items[:per_source_limit]:
                items_out.append({
                    "source": source_name,
                    "title": item.get("title", "").strip(),
                    "link": item.get("url", item.get("link", "")),
                    "published": item.get("date_published", item.get("pubDate", "")),
                    "summary": (item.get("content_text", "") or item.get("summary", ""))[:200],
                })
        else:
            # XML RSS 解析（轻量级，不依赖 feedparser）
            items = _parse_rss_xml(resp.text, per_source_limit)
            for item in items:
                item["source"] = source_name
                items_out.append(item)

    except Exception:
        pass

    return items_out


def fetch_macro_news_rss(max_items: int = 30, timeout: int = 8) -> List[Dict]:
    """
    从多个 RSS 源抓取全球宏观新闻。
    返回 [{source, title, link, published, summary}] 按时间降序。
    Uses ThreadPoolExecutor to fetch all RSS feeds concurrently.
    """
    all_items = []
    per_source_limit = max_items // len(MACRO_RSS_FEEDS)

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(_fetch_single_rss, source_name, url, per_source_limit, timeout): source_name
            for source_name, url in MACRO_RSS_FEEDS.items()
        }
        for future in as_completed(futures):
            try:
                all_items.extend(future.result())
            except Exception:
                continue

    # 按时间排序（最新在前）
    all_items.sort(key=lambda x: x.get("published", ""), reverse=True)
    return all_items[:max_items]


def _parse_rss_xml(xml_text: str, max_items: int = 10) -> List[Dict]:
    """简单的 XML RSS 解析，不依赖外部库。"""
    items = []
    # 匹配 <item> 或 <entry> 块
    item_pattern = re.compile(r'<(?:item|entry)>(.*?)</(?:item|entry)>', re.DOTALL)
    title_pattern = re.compile(r'<title[^>]*>(.*?)</title>', re.DOTALL)
    link_pattern = re.compile(r'<link[^>]*(?:href=["\']([^"\']+)["\'])?[^>]*>(.*?)</link>', re.DOTALL)
    pub_pattern = re.compile(r'<(?:pubDate|published|updated)[^>]*>(.*?)</(?:pubDate|published|updated)>', re.DOTALL)
    desc_pattern = re.compile(r'<(?:description|summary|content)[^>]*>(.*?)</(?:description|summary|content)>', re.DOTALL)

    for match in item_pattern.finditer(xml_text)[:max_items]:
        block = match.group(1)

        title_m = title_pattern.search(block)
        title = _strip_cdata(title_m.group(1)) if title_m else ""

        link_m = link_pattern.search(block)
        link = ""
        if link_m:
            link = link_m.group(1) or link_m.group(2) or ""
        link = link.strip()

        pub_m = pub_pattern.search(block)
        published = pub_m.group(1).strip() if pub_m else ""

        desc_m = desc_pattern.search(block)
        summary = _strip_cdata(desc_m.group(1))[:200] if desc_m else ""
        # 移除 HTML 标签
        summary = re.sub(r'<[^>]+>', '', summary).strip()

        items.append({
            "title": title,
            "link": link,
            "published": published,
            "summary": summary,
        })

    return items


def _strip_cdata(text: str) -> str:
    """移除 CDATA 包裹。"""
    text = re.sub(r'<!\[CDATA\[', '', text)
    text = re.sub(r'\]\]>', '', text)
    return text.strip()


def fetch_yfinance_market_news(max_items: int = 10) -> List[Dict]:
    """
    通过 yfinance 获取市场级别新闻（SPY/^GSPC 的新闻通常是宏观性质的）。
    """
    items = []
    for symbol in ["SPY", "^GSPC", "^VIX"]:
        try:
            ticker = yf.Ticker(symbol)
            news = ticker.news or []
            for n in news[:max_items // 3]:
                content = n.get("content", {})
                title = content.get("title") or n.get("title", "")
                if title:
                    items.append({
                        "source": f"Yahoo Finance ({symbol})",
                        "title": title.strip(),
                        "link": content.get("canonicalUrl", {}).get("url", ""),
                        "published": content.get("pubDate", ""),
                        "summary": content.get("summary", "")[:200],
                    })
        except Exception:
            continue
    return items


def get_all_macro_news(max_items: int = 30) -> List[Dict]:
    """合并所有宏观新闻源。"""
    rss_news = fetch_macro_news_rss(max_items=max_items)
    yf_news = fetch_yfinance_market_news(max_items=10)

    # 去重（按标题前 40 字符）
    seen = set()
    merged = []
    for item in rss_news + yf_news:
        key = item["title"][:40].lower()
        if key not in seen and item["title"]:
            seen.add(key)
            merged.append(item)

    return merged[:max_items]


# ══════════════════════════════════════════════════════════════
#  2. 持仓基本面数据
# ══════════════════════════════════════════════════════════════

FUNDAMENTAL_FIELDS = {
    "marketCap":         "Market Cap",
    "trailingPE":        "P/E (TTM)",
    "forwardPE":         "P/E (Fwd)",
    "trailingEps":       "EPS (TTM)",
    "forwardEps":        "EPS (Fwd)",
    "dividendYield":     "Div Yield",
    "revenueGrowth":     "Rev Growth",
    "earningsGrowth":    "Earn Growth",
    "profitMargins":     "Profit Margin",
    "returnOnEquity":    "ROE",
    "debtToEquity":      "D/E Ratio",
    "currentRatio":      "Current Ratio",
    "beta":              "Beta (5Y)",
    "fiftyTwoWeekHigh":  "52W High",
    "fiftyTwoWeekLow":   "52W Low",
    "averageVolume":     "Avg Volume",
}


def _fetch_single_fundamental(tk: str) -> Optional[tuple]:
    """Fetch fundamentals for a single ticker. Returns (ticker, row_dict) or None."""
    if tk.endswith("-USD"):
        return None
    try:
        info = yf.Ticker(tk).info or {}
        row = {}
        for field, label in FUNDAMENTAL_FIELDS.items():
            val = info.get(field)
            row[label] = val
        # 额外计算：距 52 周高点跌幅
        high = info.get("fiftyTwoWeekHigh")
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if high and price and high > 0:
            row["% from 52W High"] = (price - high) / high
        return (tk, row)
    except Exception:
        return None


def fetch_fundamentals(tickers: List[str]) -> pd.DataFrame:
    """
    批量获取持仓股票的基本面数据。
    返回 DataFrame: index=ticker, columns=基本面指标。
    跳过加密货币（-USD 后缀）。
    Uses ThreadPoolExecutor to fetch all tickers in parallel.
    """
    rows = {}

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_fetch_single_fundamental, tk): tk for tk in tickers}
        for future in as_completed(futures):
            try:
                result = future.result()
                if result is not None:
                    tk, row = result
                    rows[tk] = row
            except Exception:
                continue

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame.from_dict(rows, orient="index")
    df.index.name = "Ticker"
    return df


def format_fundamentals_for_display(df: pd.DataFrame) -> pd.DataFrame:
    """格式化基本面数据用于 UI 展示。"""
    if df.empty:
        return df

    display = df.copy()

    # 格式化特定列
    fmt_pct = ["Div Yield", "Rev Growth", "Earn Growth", "Profit Margin", "ROE", "% from 52W High"]
    fmt_ratio = ["P/E (TTM)", "P/E (Fwd)", "Beta (5Y)", "D/E Ratio", "Current Ratio"]
    fmt_dollar = ["EPS (TTM)", "EPS (Fwd)", "52W High", "52W Low"]

    for col in fmt_pct:
        if col in display.columns:
            display[col] = display[col].apply(
                lambda x: f"{x:.1%}" if pd.notna(x) and isinstance(x, (int, float)) else "—"
            )

    for col in fmt_ratio:
        if col in display.columns:
            display[col] = display[col].apply(
                lambda x: f"{x:.2f}" if pd.notna(x) and isinstance(x, (int, float)) else "—"
            )

    for col in fmt_dollar:
        if col in display.columns:
            display[col] = display[col].apply(
                lambda x: f"${x:.2f}" if pd.notna(x) and isinstance(x, (int, float)) else "—"
            )

    if "Market Cap" in display.columns:
        display["Market Cap"] = display["Market Cap"].apply(_fmt_market_cap)

    if "Avg Volume" in display.columns:
        display["Avg Volume"] = display["Avg Volume"].apply(
            lambda x: f"{x/1e6:.1f}M" if pd.notna(x) and isinstance(x, (int, float)) else "—"
        )

    return display


def _fmt_market_cap(val) -> str:
    """格式化市值为可读字符串。"""
    if pd.isna(val) or not isinstance(val, (int, float)):
        return "—"
    if val >= 1e12:
        return f"${val/1e12:.2f}T"
    elif val >= 1e9:
        return f"${val/1e9:.1f}B"
    elif val >= 1e6:
        return f"${val/1e6:.0f}M"
    return f"${val:,.0f}"


# ══════════════════════════════════════════════════════════════
#  3. VIX 恐慌指数 & 收益率曲线
# ══════════════════════════════════════════════════════════════

def fetch_vix_data(period: str = "1y") -> pd.DataFrame:
    """
    获取 VIX 恐慌指数历史数据。
    返回 DataFrame: Date, Close, 及计算的移动平均。
    """
    try:
        vix = yf.download("^VIX", period=period, auto_adjust=True, progress=False)
        if isinstance(vix.columns, pd.MultiIndex):
            vix = vix.droplevel(1, axis=1) if vix.columns.nlevels > 1 else vix
        if "Close" not in vix.columns:
            # 可能列名为 ticker
            vix.columns = ["Open", "High", "Low", "Close", "Volume"][:len(vix.columns)]

        df = pd.DataFrame({
            "VIX": vix["Close"].values,
        }, index=vix.index)

        df["VIX_MA20"] = df["VIX"].rolling(20).mean()
        df["VIX_MA50"] = df["VIX"].rolling(50).mean()
        return df.dropna(subset=["VIX"])
    except Exception:
        return pd.DataFrame()


def get_vix_current() -> Dict:
    """获取 VIX 当前值和关键统计。"""
    try:
        tk = yf.Ticker("^VIX")
        info = tk.info or {}
        hist = tk.history(period="5d")

        current = info.get("regularMarketPrice") or info.get("previousClose")
        if current is None and not hist.empty:
            current = float(hist["Close"].iloc[-1])

        prev_close = info.get("previousClose")
        if prev_close is None and len(hist) > 1:
            prev_close = float(hist["Close"].iloc[-2])

        change = (current - prev_close) / prev_close if current and prev_close else None

        # VIX 等级判定
        if current is None:
            level = "N/A"
            level_icon = "⚪"
        elif current < 15:
            level = "Low (Complacency)"
            level_icon = "🟢"
        elif current < 20:
            level = "Normal"
            level_icon = "🟢"
        elif current < 25:
            level = "Elevated"
            level_icon = "🟡"
        elif current < 30:
            level = "High"
            level_icon = "🟠"
        elif current < 40:
            level = "Very High (Fear)"
            level_icon = "🔴"
        else:
            level = "Extreme (Panic)"
            level_icon = "🔴"

        return {
            "current": current,
            "prev_close": prev_close,
            "change": change,
            "level": level,
            "level_icon": level_icon,
        }
    except Exception:
        return {"current": None, "level": "N/A", "level_icon": "⚪", "change": None}


# 美债收益率曲线关键期限
YIELD_CURVE_TICKERS = {
    "^IRX":  "3M",     # 3 个月 T-Bill
    "^FVX":  "5Y",     # 5 年期
    "^TNX":  "10Y",    # 10 年期
    "^TYX":  "30Y",    # 30 年期
}

# 更完整的收益率曲线（通过 FRED 或 yfinance）
YIELD_TICKERS_FULL = {
    "^IRX":  ("3M",  0.25),
    "^FVX":  ("5Y",  5.0),
    "^TNX":  ("10Y", 10.0),
    "^TYX":  ("30Y", 30.0),
}


def fetch_yield_curve() -> Tuple[pd.DataFrame, Dict]:
    """
    获取当前美国国债收益率曲线。
    返回:
      - DataFrame: 期限 vs 收益率（当前 + 30天前 + 90天前）
      - Dict: 曲线分析结果（倒挂判定、期限利差等）
    """
    tickers = list(YIELD_TICKERS_FULL.keys())

    try:
        # 下载 90 天数据
        raw = yf.download(
            tickers,
            period="90d",
            auto_adjust=True,
            progress=False,
        )

        if isinstance(raw.columns, pd.MultiIndex):
            close = raw["Close"]
            if isinstance(close.columns, pd.MultiIndex):
                close = close.droplevel(0, axis=1)
        else:
            close = raw

        close = close.ffill().dropna(how="all")

        if close.empty:
            return pd.DataFrame(), {}

        # 当前收益率
        current = close.iloc[-1]
        # 30天前
        idx_30d = max(0, len(close) - 22)
        month_ago = close.iloc[idx_30d]
        # 90天前
        quarter_ago = close.iloc[0]

        rows = []
        for tk, (label, years) in YIELD_TICKERS_FULL.items():
            if tk in current.index:
                rows.append({
                    "Maturity": label,
                    "Years": years,
                    "Current (%)": float(current.get(tk, np.nan)),
                    "30d Ago (%)": float(month_ago.get(tk, np.nan)),
                    "90d Ago (%)": float(quarter_ago.get(tk, np.nan)),
                })

        curve_df = pd.DataFrame(rows)

        # 分析
        analysis = {}
        c3m = current.get("^IRX")
        c10y = current.get("^TNX")
        c30y = current.get("^TYX")

        if c3m is not None and c10y is not None:
            spread_3m_10y = float(c10y - c3m)
            analysis["3M-10Y Spread"] = spread_3m_10y
            analysis["inverted_3m_10y"] = spread_3m_10y < 0

        if c10y is not None and c30y is not None:
            spread_10y_30y = float(c30y - c10y)
            analysis["10Y-30Y Spread"] = spread_10y_30y

        if c3m is not None and c10y is not None:
            if spread_3m_10y < -0.5:
                analysis["curve_status"] = "Deeply Inverted"
                analysis["curve_icon"] = "🔴"
            elif spread_3m_10y < 0:
                analysis["curve_status"] = "Inverted"
                analysis["curve_icon"] = "🟠"
            elif spread_3m_10y < 0.5:
                analysis["curve_status"] = "Flat"
                analysis["curve_icon"] = "🟡"
            else:
                analysis["curve_status"] = "Normal (Steep)"
                analysis["curve_icon"] = "🟢"

        return curve_df, analysis

    except Exception:
        return pd.DataFrame(), {}


# ══════════════════════════════════════════════════════════════
#  3b. CNN Fear & Greed Index
# ══════════════════════════════════════════════════════════════

FEAR_GREED_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"

FEAR_GREED_RATINGS = {
    "extreme fear": {"icon": "🔴", "color": "#C92A2A"},
    "fear":         {"icon": "🟠", "color": "#E67700"},
    "neutral":      {"icon": "🟡", "color": "#F59F00"},
    "greed":        {"icon": "🟢", "color": "#37B24D"},
    "extreme greed": {"icon": "🟢", "color": "#2B8A3E"},
}


def fetch_fear_greed(timeout: int = 10) -> Dict:
    """
    Fetch CNN Fear & Greed Index.
    Returns {score, rating, rating_icon, previous_close, one_week_ago,
             one_month_ago, one_year_ago, timestamp, historical, sub_indices}.
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; PortfolioRisk/1.0)",
            "Accept": "application/json",
        }
        resp = requests.get(FEAR_GREED_URL, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()

        fg = data.get("fear_and_greed", {})
        score = fg.get("score")
        rating = fg.get("rating", "").lower()
        rating_meta = FEAR_GREED_RATINGS.get(rating, {"icon": "⚪", "color": "#64748B"})

        result = {
            "score": round(score, 1) if score is not None else None,
            "rating": rating,
            "rating_display": rating.title(),
            "rating_icon": rating_meta["icon"],
            "rating_color": rating_meta["color"],
            "previous_close": fg.get("previous_close"),
            "one_week_ago": fg.get("previous_1_week"),
            "one_month_ago": fg.get("previous_1_month"),
            "one_year_ago": fg.get("previous_1_year"),
            "timestamp": fg.get("timestamp", ""),
        }

        # Historical data
        fgh = data.get("fear_and_greed_historical", {})
        hist_raw = fgh.get("data", [])
        if hist_raw:
            hist_df = pd.DataFrame(hist_raw)
            if "x" in hist_df.columns and "y" in hist_df.columns:
                hist_df["date"] = pd.to_datetime(hist_df["x"], unit="ms")
                hist_df = hist_df.rename(columns={"y": "score"})
                result["historical"] = hist_df[["date", "score"]].dropna()
            else:
                result["historical"] = pd.DataFrame()
        else:
            result["historical"] = pd.DataFrame()

        # Sub-indices
        sub_keys = [
            ("market_momentum_sp500", "S&P 500 Momentum"),
            ("stock_price_strength", "Stock Price Strength"),
            ("stock_price_breadth", "Stock Price Breadth"),
            ("put_call_options", "Put/Call Options"),
            ("market_volatility_vix", "Market Volatility (VIX)"),
            ("junk_bond_demand", "Junk Bond Demand"),
            ("safe_haven_demand", "Safe Haven Demand"),
        ]
        sub_indices = {}
        for key, label in sub_keys:
            sub_data = data.get(key, {})
            if isinstance(sub_data, dict) and "score" in sub_data:
                sub_indices[label] = {
                    "score": round(sub_data["score"], 1),
                    "rating": sub_data.get("rating", "").title(),
                }
        result["sub_indices"] = sub_indices

        return result
    except Exception:
        return {"score": None, "rating": "N/A", "rating_icon": "⚪", "sub_indices": {}}


# ══════════════════════════════════════════════════════════════
#  4. AI 综合风险简报
# ══════════════════════════════════════════════════════════════

def build_ai_risk_briefing(
    report,
    weights: Dict[str, float],
    vix_info: Dict,
    yield_analysis: Dict,
    fundamentals_df: pd.DataFrame,
    macro_news: List[Dict],
    sentiment_data: Optional[Dict] = None,
    lang: str = "zh",
) -> str:
    """
    综合所有维度的数据，生成结构化的 AI 风险简报提示词。
    返回文本供 LLM 生成最终简报。
    """
    sections = []

    # ── A. 市场情绪概览 ──────────────────────────────────────
    sections.append("## A. 市场情绪概览")

    if vix_info.get("current") is not None:
        vix_val = vix_info["current"]
        vix_change = vix_info.get("change")
        change_str = f" ({vix_change:+.1%} vs prev close)" if vix_change else ""
        sections.append(f"  VIX 恐慌指数: {vix_val:.2f}{change_str} — {vix_info['level']}")

    if yield_analysis:
        status = yield_analysis.get("curve_status", "N/A")
        spread = yield_analysis.get("3M-10Y Spread")
        spread_str = f", 3M-10Y spread: {spread:+.2f}%" if spread is not None else ""
        sections.append(f"  收益率曲线: {status}{spread_str}")

    sections.append("")

    # ── B. 宏观新闻摘要 ──────────────────────────────────────
    if macro_news:
        sections.append("## B. 最新宏观新闻（前 10 条）")
        for i, item in enumerate(macro_news[:10], 1):
            sections.append(f"  {i}. [{item['source']}] {item['title']}")
        sections.append("")

    # ── C. 持仓基本面快照 ─────────────────────────────────────
    if fundamentals_df is not None and not fundamentals_df.empty:
        sections.append("## C. 持仓基本面快照（前 10 大持仓）")
        top_tickers = sorted(weights, key=lambda x: -weights[x])[:10]
        for tk in top_tickers:
            if tk in fundamentals_df.index:
                row = fundamentals_df.loc[tk]
                pe = row.get("P/E (TTM)")
                mcap = row.get("Market Cap")
                eps = row.get("EPS (TTM)")
                dy = row.get("Div Yield")
                rg = row.get("Rev Growth")
                pct_high = row.get("% from 52W High")

                parts = [f"  {tk} (wt: {weights[tk]:.1%}):"]
                if pd.notna(pe):
                    parts.append(f"P/E={pe:.1f}")
                if pd.notna(mcap):
                    parts.append(f"MCap={_fmt_market_cap(mcap)}")
                if pd.notna(eps):
                    parts.append(f"EPS=${eps:.2f}")
                if pd.notna(dy) and isinstance(dy, (int, float)):
                    parts.append(f"Div={dy:.1%}")
                if pd.notna(rg) and isinstance(rg, (int, float)):
                    parts.append(f"RevGr={rg:.1%}")
                if pd.notna(pct_high) and isinstance(pct_high, (int, float)):
                    parts.append(f"vs52WH={pct_high:.1%}")
                sections.append("  ".join(parts))
        sections.append("")

    # ── D. 量化风险指标（简缩版）───────────────────────────────
    sections.append("## D. 核心量化风险指标")
    sections.append(f"  VaR 95%: {report.var_95:.2%} | VaR 99%: {report.var_99:.2%} | CVaR 95%: {report.cvar_95:.2%}")
    sections.append(f"  年化波动率: {report.annual_volatility:.2%} | 夏普: {report.sharpe_ratio:.2f} | 最大回撤: {report.max_drawdown:.2%}")
    sections.append(f"  压力损失: {report.stress_loss:.2%}")

    if report.margin_call_info and report.margin_call_info.get("has_margin"):
        mi = report.margin_call_info
        sections.append(f"  杠杆: {mi['leverage']:.2f}x | 距强平: {mi['distance_to_call_pct']:.1%}")
    sections.append("")

    # ── E. 情绪得分（如有）────────────────────────────────────
    if sentiment_data:
        sections.append("## E. 个股情绪评分")
        for tk, data in sorted(sentiment_data.items(), key=lambda x: x[1]["score"]):
            sections.append(f"  {tk}: {data['score']:+d}/10 — {data['summary'][:60]}")
        sections.append("")

    # ── 生成提示 ──────────────────────────────────────────────
    if lang == "zh":
        instruction = """## 请求
基于以上所有信息，生成一份简洁的综合风险简报（3-5 段），包括：
1. **市场环境判断** — VIX、收益率曲线、宏观新闻的综合含义
2. **持仓风险诊断** — 基于基本面数据，哪些持仓估值偏高/低？哪些有增长动力？
3. **量化风险警示** — VaR、压力损失、杠杆等量化指标的含义
4. **可操作建议** — 基于当前市场环境，建议的具体调仓/对冲行动
5. **关键监控事项** — 未来一周需要重点关注的事件或指标

语气：机构晨会简报风格，简洁有力，引用具体数字。"""
    else:
        instruction = """## Request
Based on all the information above, generate a concise comprehensive risk briefing (3-5 paragraphs):
1. **Market Environment** — What VIX, yield curve, and macro news collectively signal
2. **Holdings Risk Diagnosis** — Which holdings are overvalued/undervalued based on fundamentals? Growth catalysts?
3. **Quantitative Risk Alerts** — VaR, stress loss, leverage implications
4. **Actionable Recommendations** — Specific rebalancing/hedging actions given current conditions
5. **Key Watchlist Items** — Events or indicators to monitor in the coming week

Tone: Institutional morning briefing style, concise and authoritative, cite specific numbers."""

    sections.append(instruction)

    return "\n".join(sections)


def build_market_intelligence_context(
    vix_info: Dict,
    yield_analysis: Dict,
    yield_curve_df: pd.DataFrame,
    fundamentals_df: pd.DataFrame,
    macro_news: List[Dict],
    fear_greed_data: Optional[Dict] = None,
) -> str:
    """
    构建市场情报文本，注入到 AI 聊天的系统上下文中。
    """
    lines = []

    # VIX
    lines.append("")
    lines.append("## 17. Market Sentiment - VIX Fear Index")
    if vix_info.get("current") is not None:
        v = vix_info
        change_str = f" ({v['change']:+.1%})" if v.get("change") else ""
        lines.append(f"  VIX: {v['current']:.2f}{change_str} — {v['level']}")
        if v["current"] and v["current"] > 25:
            lines.append("  ⚠ Elevated fear — consider hedging or reducing risk exposure")
    else:
        lines.append("  VIX data unavailable")
    lines.append("")

    # CNN Fear & Greed Index
    if fear_greed_data and fear_greed_data.get("score") is not None:
        fg = fear_greed_data
        lines.append("## 18. CNN Fear & Greed Index")
        lines.append(f"  Score: {fg['score']}/100 - {fg.get('rating_display', 'N/A')} {fg.get('rating_icon', '')}")
        if fg.get("previous_close"):
            lines.append(f"  Previous Close: {fg['previous_close']:.1f}")
        if fg.get("one_week_ago"):
            lines.append(f"  1 Week Ago: {fg['one_week_ago']:.1f}")
        if fg.get("one_month_ago"):
            lines.append(f"  1 Month Ago: {fg['one_month_ago']:.1f}")
        for name, sub in fg.get("sub_indices", {}).items():
            lines.append(f"  {name}: {sub['score']:.1f} ({sub['rating']})")
        if fg["score"] <= 25:
            lines.append("  WARNING: Extreme Fear - historically a contrarian BUY signal")
        elif fg["score"] >= 75:
            lines.append("  WARNING: Extreme Greed - historically a contrarian SELL signal")
        lines.append("")

    # Yield Curve
    lines.append("## 19. US Treasury Yield Curve")
    if yield_analysis:
        status = yield_analysis.get("curve_status", "N/A")
        icon = yield_analysis.get("curve_icon", "")
        lines.append(f"  Status: {icon} {status}")
        if "3M-10Y Spread" in yield_analysis:
            lines.append(f"  3M-10Y Spread: {yield_analysis['3M-10Y Spread']:+.2f}%")
        if "10Y-30Y Spread" in yield_analysis:
            lines.append(f"  10Y-30Y Spread: {yield_analysis['10Y-30Y Spread']:+.2f}%")
        if yield_analysis.get("inverted_3m_10y"):
            lines.append("  ⚠ Inverted yield curve — historically a recession signal")
    if yield_curve_df is not None and not yield_curve_df.empty:
        lines.append("  Current rates:")
        for _, row in yield_curve_df.iterrows():
            curr = row.get("Current (%)")
            if pd.notna(curr):
                lines.append(f"    {row['Maturity']}: {curr:.2f}%")
    lines.append("")

    # Fundamentals summary
    if fundamentals_df is not None and not fundamentals_df.empty:
        lines.append("## 20. Holdings Fundamentals Snapshot")
        for tk in fundamentals_df.index[:15]:
            row = fundamentals_df.loc[tk]
            pe = row.get("P/E (TTM)")
            mcap = row.get("Market Cap")
            pct_high = row.get("% from 52W High")
            parts = [f"  {tk}:"]
            if pd.notna(pe):
                parts.append(f"P/E={pe:.1f}")
            if pd.notna(mcap):
                parts.append(f"MCap={_fmt_market_cap(mcap)}")
            if pd.notna(pct_high) and isinstance(pct_high, (int, float)):
                parts.append(f"vs52WH={pct_high:.1%}")
            lines.append(" ".join(parts))
        # Flag overvalued
        if "P/E (TTM)" in fundamentals_df.columns:
            high_pe = fundamentals_df[fundamentals_df["P/E (TTM)"] > 40].index.tolist()
            if high_pe:
                lines.append(f"  ⚠ High P/E (>40): {', '.join(high_pe)}")
        lines.append("")

    # Macro news headlines
    if macro_news:
        lines.append("## 21. Latest Macro News Headlines")
        for item in macro_news[:8]:
            lines.append(f"  • [{item['source']}] {item['title'][:100]}")
        lines.append("")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
#  5. 简易 DCF 估值 (Gordon Growth Model)
# ══════════════════════════════════════════════════════════════

def compute_simple_dcf(ticker: str, discount_rate: float = 0.10) -> Dict:
    """Backwards-compatible alias for compute_advanced_dcf."""
    return compute_advanced_dcf(ticker)


def compute_advanced_dcf(
    ticker: str,
    risk_free_rate: float = 0.045,
    market_return: float = 0.10,
) -> Dict:
    """
    Hybrid valuation model:
      1) Primary: Two-Stage FCF DCF (if freeCashflow available)
      2) Fallback: P/E Multiple model (if EPS available but no FCF)
      3) Skip: ETFs, crypto, and tickers with no fundamental data

    Returns dict: {intrinsic_value, current_price, upside_pct, verdict,
                   method, discount_rate, ...}
    """
    _NA = {
        "intrinsic_value": None, "current_price": None,
        "upside_pct": None, "verdict": "N/A", "method": "N/A",
    }

    # Skip crypto and known non-equity tickers
    if ticker.endswith("-USD"):
        return {**_NA, "verdict": "Crypto", "method": "Skipped (Crypto)"}

    try:
        info = yf.Ticker(ticker).info or {}
        qtype = info.get("quoteType", "")

        # Skip ETFs
        if qtype in ("ETF", "MUTUALFUND") or ticker in ("SPY", "QQQ", "GLD", "TQQQ", "COPX", "SLV"):
            price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("navPrice")
            return {
                **_NA,
                "current_price": round(price, 2) if price else None,
                "verdict": "ETF",
                "method": "Skipped (ETF)",
            }

        current_price = info.get("currentPrice") or info.get("regularMarketPrice")
        if not current_price or current_price <= 0:
            return _NA

        shares = info.get("sharesOutstanding")
        beta = info.get("beta")
        if beta is None or not isinstance(beta, (int, float)) or np.isnan(beta):
            logger.warning("dcf.beta_fallback", ticker=ticker, reason="beta unavailable, defaulting to 1.0")
            beta = 1.0

        # CAPM discount rate
        cost_of_equity = risk_free_rate + beta * (market_return - risk_free_rate)
        discount_rate = max(0.06, min(cost_of_equity, 0.15))

        # Growth rates
        raw_growth = info.get("earningsGrowth") or info.get("revenueGrowth")
        if raw_growth is None or not isinstance(raw_growth, (int, float)):
            raw_growth = 0.05
        short_growth = max(0.02, min(raw_growth, 0.25))

        terminal_growth = 0.025
        if discount_rate <= terminal_growth:
            discount_rate = terminal_growth + 0.03

        # ═══════════════════════════════════════════════════════
        #  Method 1: Two-Stage FCF DCF (preferred)
        # ═══════════════════════════════════════════════════════
        fcf = info.get("freeCashflow")
        total_cash = info.get("totalCash") or 0
        total_debt = info.get("totalDebt") or 0

        if fcf and shares and fcf > 0 and shares > 0:
            pv_fcf_total = 0.0
            projected_fcf = float(fcf)
            for year in range(1, 6):
                projected_fcf *= (1 + short_growth)
                pv_fcf_total += projected_fcf / ((1 + discount_rate) ** year)

            terminal_value = projected_fcf * (1 + terminal_growth) / (discount_rate - terminal_growth)
            pv_terminal = terminal_value / ((1 + discount_rate) ** 5)

            enterprise_value = pv_fcf_total + pv_terminal
            equity_value = enterprise_value + total_cash - total_debt

            if equity_value > 0:
                intrinsic = equity_value / shares
                upside_pct = (intrinsic - current_price) / current_price
                verdict = "Undervalued" if upside_pct > 0.15 else ("Overvalued" if upside_pct < -0.15 else "Fair")
                return {
                    "intrinsic_value": round(intrinsic, 2),
                    "current_price": round(current_price, 2),
                    "upside_pct": round(upside_pct, 4),
                    "verdict": verdict,
                    "method": "2-Stage FCF DCF",
                    "discount_rate": round(discount_rate, 4),
                    "short_term_growth": round(short_growth, 4),
                    "fcf": fcf,
                    "ev": round(enterprise_value, 0),
                    "equity_value": round(equity_value, 0),
                }

        # ═══════════════════════════════════════════════════════
        #  Method 2: P/E Multiple Fallback (when no FCF)
        # ═══════════════════════════════════════════════════════
        eps = info.get("forwardEps") or info.get("trailingEps")
        if eps and isinstance(eps, (int, float)) and eps > 0:
            # Use sector-average P/E or a conservative multiple
            forward_pe = info.get("forwardPE")
            trailing_pe = info.get("trailingPE")
            sector_pe = info.get("sectorPE")  # may not exist

            # Target P/E: use 1/discount_rate as theoretical fair P/E, clamped
            fair_pe = 1.0 / discount_rate
            fair_pe = max(8, min(fair_pe, 30))  # clamp 8x-30x

            intrinsic = eps * fair_pe
            if intrinsic > 0:
                upside_pct = (intrinsic - current_price) / current_price
                verdict = "Undervalued" if upside_pct > 0.15 else ("Overvalued" if upside_pct < -0.15 else "Fair")
                return {
                    "intrinsic_value": round(intrinsic, 2),
                    "current_price": round(current_price, 2),
                    "upside_pct": round(upside_pct, 4),
                    "verdict": verdict,
                    "method": f"P/E Multiple ({fair_pe:.0f}x)",
                    "discount_rate": round(discount_rate, 4),
                    "short_term_growth": round(short_growth, 4),
                }

        # ═══════════════════════════════════════════════════════
        #  No usable data
        # ═══════════════════════════════════════════════════════
        return {
            **_NA,
            "current_price": round(current_price, 2),
            "method": "No FCF or EPS data",
        }

    except Exception:
        return _NA


# ══════════════════════════════════════════════════════════════
#  Insider Transaction Signals
# ══════════════════════════════════════════════════════════════

def _fetch_single_insider(tk: str) -> Optional[tuple]:
    """Fetch insider signals for a single ticker. Returns (ticker, result_dict) or None."""
    if tk.endswith("-USD"):
        return None

    cutoff = datetime.now() - timedelta(days=90)

    try:
        txn_df = yf.Ticker(tk).insider_transactions

        if txn_df is None or txn_df.empty:
            return (tk, {
                "net_shares": 0,
                "direction": "No Data",
                "count": 0,
                "recent_txns": [],
            })

        # Determine the date column name
        date_col = "Start Date" if "Start Date" in txn_df.columns else "Date"

        if date_col in txn_df.columns:
            txn_df[date_col] = pd.to_datetime(txn_df[date_col], errors="coerce")
            txn_df = txn_df.dropna(subset=[date_col])
            txn_df = txn_df[txn_df[date_col] >= cutoff]

        if txn_df.empty:
            return (tk, {
                "net_shares": 0,
                "direction": "No Activity",
                "count": 0,
                "recent_txns": [],
            })

        net = int(txn_df["Shares"].sum()) if "Shares" in txn_df.columns else 0

        if net > 0:
            direction = "Net Buyer"
        elif net < 0:
            direction = "Net Seller"
        else:
            direction = "No Activity"

        count = len(txn_df)

        # Collect top 3 recent transactions
        recent_txns: List[str] = []
        top_rows = txn_df.head(3)
        for _, row in top_rows.iterrows():
            shares = row.get("Shares", 0)
            if shares >= 0:
                recent_txns.append(f"BUY {abs(int(shares))} shares")
            else:
                recent_txns.append(f"SELL {abs(int(shares))} shares")

        return (tk, {
            "net_shares": net,
            "direction": direction,
            "count": count,
            "recent_txns": recent_txns,
        })

    except Exception:
        return (tk, {
            "net_shares": 0,
            "direction": "No Data",
            "count": 0,
            "recent_txns": [],
        })


def fetch_insider_signals(tickers: List[str]) -> Dict[str, dict]:
    """
    Fetch insider transactions for each ticker, compute net buy/sell direction.
    Returns {ticker: {net_shares: int, direction: str, count: int, recent_txns: list}}.
    Uses ThreadPoolExecutor to fetch all tickers in parallel.
    """
    results: Dict[str, dict] = {}

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_fetch_single_insider, tk): tk for tk in tickers}
        for future in as_completed(futures):
            try:
                result = future.result()
                if result is not None:
                    tk, data = result
                    results[tk] = data
            except Exception:
                continue

    return results


# ══════════════════════════════════════════════════════════════
#  Technical Signals (RSI & SMA50)
# ══════════════════════════════════════════════════════════════

def compute_technical_signals(prices: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate RSI(14) and SMA50 position for each asset from price data.
    Returns DataFrame indexed by ticker with columns: RSI, RSI_Signal, SMA50, Price, Price_vs_SMA50, Pct_vs_SMA50.
    """
    records: List[dict] = []

    for col in prices.columns:
        series = prices[col].dropna()

        # --- RSI(14) ---
        delta = prices[col].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()
        rs = avg_gain / avg_loss
        rsi_series = 100 - (100 / (1 + rs))
        rsi_val = rsi_series.dropna().iloc[-1] if not rsi_series.dropna().empty else None

        if rsi_val is not None and not np.isnan(rsi_val):
            rsi_val = round(rsi_val, 2)
            if rsi_val > 70:
                rsi_signal = "Overbought"
            elif rsi_val < 30:
                rsi_signal = "Oversold"
            else:
                rsi_signal = "Neutral"
        else:
            rsi_val = "N/A"
            rsi_signal = "N/A"

        # --- SMA50 ---
        sma50_series = prices[col].rolling(50).mean()
        sma50_val = sma50_series.dropna().iloc[-1] if not sma50_series.dropna().empty else None

        price_val = prices[col].iloc[-1] if len(prices[col]) > 0 else None

        if (
            sma50_val is not None
            and price_val is not None
            and not np.isnan(sma50_val)
            and not np.isnan(price_val)
        ):
            sma50_val = round(sma50_val, 2)
            price_val_round = round(price_val, 2)
            price_vs_sma = "Above" if price_val > sma50_val else "Below"
            pct_vs_sma = round((price_val - sma50_val) / sma50_val * 100, 2) if sma50_val != 0 else 0.0
        else:
            sma50_val = "N/A"
            price_val_round = round(price_val, 2) if price_val is not None and not np.isnan(price_val) else "N/A"
            price_vs_sma = "N/A"
            pct_vs_sma = "N/A"

        records.append({
            "Ticker": col,
            "RSI": rsi_val,
            "RSI_Signal": rsi_signal,
            "SMA50": sma50_val,
            "Price": price_val_round,
            "Price_vs_SMA50": price_vs_sma,
            "Pct_vs_SMA50": pct_vs_sma,
        })

    return pd.DataFrame(records).set_index("Ticker")


# ══════════════════════════════════════════════════════════════
#  8. Reddit 散户情绪（Apify）
# ══════════════════════════════════════════════════════════════

def fetch_reddit_sentiment_apify(
    tickers: List[str],
    max_posts: int = 15,
    apify_key: Optional[str] = None,
) -> Dict[str, List[Dict]]:
    """
    Fetch Reddit posts via Apify. Two strategies:
    1. Hot posts from r/wallstreetbets and r/stocks (general market buzz)
    2. Filter/tag posts that mention specific tickers

    Returns {"_hot": [general hot posts], "NVDA": [ticker-specific], ...}
    """
    if not apify_key:
        return {"_hot": [], **{tk: [] for tk in tickers}}

    all_posts = []

    # Detect crypto tickers (ending in -USD) — only pay the crypto-subreddit
    # latency cost if the portfolio actually holds crypto.
    has_crypto = any(
        isinstance(tk, str) and tk.upper().endswith("-USD") for tk in (tickers or [])
    )

    # Strategy A: Use Apify's web scraper to fetch Reddit JSON API directly
    # Reddit exposes .json endpoints that don't need authentication
    subreddits = ["wallstreetbets", "stocks"]
    if has_crypto:
        subreddits += ["cryptocurrency", "CryptoMarkets"]
    for sub in subreddits:
        try:
            # Reddit's public JSON API (no auth needed, just add .json)
            url = f"https://www.reddit.com/r/{sub}/hot.json?limit=25&t=day"
            headers = {"User-Agent": "MindMarketAI/1.0 (Portfolio Risk Dashboard)"}
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                for child in data.get("data", {}).get("children", []):
                    post = child.get("data", {})
                    title = post.get("title", "")
                    text = post.get("selftext", "")
                    score = post.get("score", 0)
                    num_comments = post.get("num_comments", 0)
                    created = post.get("created_utc", 0)
                    permalink = post.get("permalink", "")
                    if title and score > 5:  # filter low-quality
                        all_posts.append({
                            "title": title[:200],
                            "text": (text or "")[:500],
                            "upvotes": int(score),
                            "comments": int(num_comments),
                            "subreddit": sub,
                            "url": f"https://reddit.com{permalink}" if permalink else "",
                        })
        except Exception:
            continue

    # Strategy B: If Reddit JSON API fails (rate limited), try Apify actor as backup
    if not all_posts:
        try:
            from apify_client import ApifyClient
            client = ApifyClient(apify_key)

            run_input = {
                "startUrls": [
                    {"url": "https://www.reddit.com/r/wallstreetbets/hot/"},
                    {"url": "https://www.reddit.com/r/stocks/hot/"},
                ],
                "maxItems": 30,
                "sort": "hot",
                "time": "day",
            }

            # Try multiple actor IDs (Apify ecosystem varies)
            for actor_id in ["trudax/reddit-scraper", "apify/reddit-scraper", "okheydk/reddit-scraper"]:
                try:
                    run = client.actor(actor_id).call(
                        run_input=run_input,
                        timeout_secs=45,
                        memory_mbytes=256,
                    )
                    for item in client.dataset(run["defaultDatasetId"]).iterate_items():
                        title = item.get("title", "")
                        text = item.get("body", item.get("text", item.get("selftext", "")))
                        score = item.get("score", item.get("upVotes", item.get("ups", 0)))
                        comments = item.get("numberOfComments", item.get("num_comments", 0))
                        if title:
                            all_posts.append({
                                "title": title[:200],
                                "text": (text or "")[:500],
                                "upvotes": int(score) if score else 0,
                                "comments": int(comments) if comments else 0,
                                "subreddit": "wsb/stocks",
                                "url": item.get("url", ""),
                            })
                    if all_posts:
                        break  # found working actor
                except Exception:
                    continue
        except ImportError:
            pass

    # Sort all posts by upvotes
    all_posts.sort(key=lambda x: -x["upvotes"])

    # Tag posts by ticker mention — use word-boundary regex so "S" doesn't
    # match every post containing the letter S, and "AA" doesn't match "AAPL".
    results = {"_hot": all_posts[:max_posts]}

    # Common crypto aliases — when a BTC-USD ticker is in the portfolio we
    # should also match posts mentioning "Bitcoin", etc.
    crypto_aliases = {
        "BTC": ["Bitcoin"],
        "ETH": ["Ethereum"],
        "SOL": ["Solana"],
        "XRP": ["Ripple"],
        "ADA": ["Cardano"],
        "LINK": ["Chainlink"],
        "DOGE": ["Dogecoin"],
    }

    for tk in tickers:
        tk_clean = tk.upper().replace("-USD", "")
        # Build alternation list: ticker symbol + any known aliases
        alts = [re.escape(tk_clean)]
        for alias in crypto_aliases.get(tk_clean, []):
            alts.append(re.escape(alias))
        alt_group = "|".join(alts)
        # \b handles word boundaries; $ prefix optional.
        # (?i) makes aliases like "Bitcoin" match regardless of case in the
        # uppercased search_text below (still safe because search_text is .upper()).
        pattern = re.compile(rf'(?<![A-Z])\$?(?:{alt_group})(?![A-Z])', re.IGNORECASE)
        matched = []
        for p in all_posts:
            search_text = (p["title"] + " " + p["text"]).upper()
            if pattern.search(search_text):
                matched.append(p)
        results[tk] = matched[:max_posts]

    return results


def format_reddit_for_llm(posts: List[Dict], ticker: str = "") -> str:
    """Format Reddit posts into text for LLM analysis."""
    if not posts:
        return ""
    lines = []
    for p in posts[:12]:
        sub = p.get("subreddit", "")
        upvotes = p.get("upvotes", 0)
        comments = p.get("comments", 0)
        lines.append(f"- [{sub}] {p['title']} [+{upvotes}, {comments} comments]")
        if p.get("text"):
            lines.append(f"  {p['text'][:200]}")
    return "\n".join(lines)


def fetch_stock_news_fmp(
    tickers: Tuple[str, ...],
    fmp_key: str,
    max_per_ticker: int = 8,
) -> Dict[str, List[str]]:
    """
    Fetch recent news headlines per ticker from Financial Modeling Prep.

    This is a SUPPLEMENT to yfinance news (fetch_asset_news), not a replacement.
    FMP typically has better coverage/freshness for US equities but charges per
    call; yfinance remains the default free source. Callers can merge/dedupe
    the two outputs as needed — the return shape here matches fetch_asset_news
    ({ticker: [title, title, ...]}) so it's drop-in compatible.

    Skips tickers with a -USD suffix (crypto — FMP stock_news endpoint is for
    equities only) and returns empty lists for any ticker whose API call fails,
    so a partial outage never blocks the caller.
    """
    results: Dict[str, List[str]] = {}
    if not tickers:
        return results
    if not fmp_key:
        # Silent fallback — return empty lists for every requested ticker so
        # callers can still iterate the dict without KeyErrors.
        return {tk: [] for tk in tickers}

    for tk in tickers:
        if not isinstance(tk, str) or not tk:
            continue
        if tk.upper().endswith("-USD"):
            # Crypto — FMP stock_news doesn't cover these; skip silently.
            results[tk] = []
            continue
        try:
            url = (
                f"{FMP_BASE}/stock_news"
                f"?tickers={tk.upper()}&limit={int(max_per_ticker)}&apikey={fmp_key}"
            )
            resp = requests.get(url, timeout=10)
            if resp.status_code != 200:
                results[tk] = []
                continue
            data = resp.json()
            if not isinstance(data, list):
                results[tk] = []
                continue
            titles = [
                str(item.get("title", "")).strip()
                for item in data
                if isinstance(item, dict) and item.get("title")
            ]
            results[tk] = titles[:max_per_ticker]
        except Exception:
            # Silent on failures — news is best-effort, never block the caller.
            results[tk] = []

    return results


# ══════════════════════════════════════════════════════════════
#  9. FMP 财报电话会议逐字稿 + Claude 深度分析
# ══════════════════════════════════════════════════════════════

FMP_BASE = "https://financialmodelingprep.com/api/v3"


def fetch_latest_transcript_fmp(ticker: str, fmp_key: str) -> Dict:
    """
    Fetch the latest earnings call transcript from Financial Modeling Prep.
    Returns: {date, quarter, year, content, ticker} or {error: str}.
    """
    if not fmp_key:
        return {"error": "FMP_API_KEY not configured"}

    url = f"{FMP_BASE}/earning_call_transcript/{ticker.upper()}?apikey={fmp_key}"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if not data or not isinstance(data, list) or len(data) == 0:
            return {"error": f"No transcript available for {ticker}"}

        latest = data[0]  # FMP returns most recent first
        result = {
            "ticker": ticker.upper(),
            "date": latest.get("date", ""),
            "quarter": latest.get("quarter", ""),
            "year": latest.get("year", ""),
            "content": latest.get("content", ""),
        }
        # Also grab previous quarter for QoQ delta analysis
        if len(data) >= 2:
            prev = data[1]
            result["prev_quarter"] = prev.get("quarter", "")
            result["prev_year"] = prev.get("year", "")
            result["prev_content"] = prev.get("content", "")
            result["prev_date"] = prev.get("date", "")
        return result
    except requests.exceptions.HTTPError as e:
        if "403" in str(e):
            return {"error": "FMP API key invalid or plan does not include transcripts"}
        return {"error": f"FMP API error: {e}"}
    except Exception as e:
        return {"error": f"Failed to fetch transcript: {e}"}


def analyze_transcript_with_claude(
    ticker: str,
    transcript_data: Dict,
    anthropic_api_key: str,
) -> Dict:
    """
    Send earnings call transcript(s) to Claude for deep NLP analysis.
    If two quarters are available, performs QoQ sentiment delta analysis.
    Returns structured JSON with management tone, guidance, capex, Q&A highlights,
    and sentiment_deltas (if 2 quarters provided).
    """
    import json as _json

    content = transcript_data.get("content", "")
    if not content:
        return {"error": "No transcript content to analyze"}

    quarter = transcript_data.get("quarter", "?")
    year = transcript_data.get("year", "?")
    date = transcript_data.get("date", "?")
    prev_content = transcript_data.get("prev_content", "")
    prev_q = transcript_data.get("prev_quarter", "")
    prev_y = transcript_data.get("prev_year", "")
    has_prev = bool(prev_content)

    # Build transcript text — truncate each to fit within token limits
    if has_prev:
        current_trunc = content[:18000]
        prev_trunc = prev_content[:12000]
        transcript_block = (
            f"=== CURRENT QUARTER: Q{quarter} {year} ({date}) ===\n{current_trunc}\n\n"
            f"=== PREVIOUS QUARTER: Q{prev_q} {prev_y} ===\n{prev_trunc}"
        )
    else:
        transcript_block = content[:30000]

    # Build prompt
    delta_field = ""
    if has_prev:
        delta_field = (
            f'  "sentiment_deltas": [\n'
            f'    {{"topic": "<Revenue Guidance|CAPEX|Macro Outlook|Competition|Margins>", '
            f'"direction": "<up|down|flat>", '
            f'"detail": "<1-sentence describing how management tone changed from Q{prev_q} to Q{quarter}>"}}\n'
            f'  ],\n'
        )

    prompt = (
        f"You are a senior buy-side equity analyst at a top-tier hedge fund.\n"
        f"Analyze {'these two quarters of' if has_prev else 'this'} earnings call transcript(s) for {ticker}.\n"
        f"{'Compare Q' + str(prev_q) + ' ' + str(prev_y) + ' vs Q' + str(quarter) + ' ' + str(year) + ' to identify marginal changes in management sentiment.' if has_prev else ''}\n\n"
        f"Return ONLY valid JSON:\n"
        f'{{\n'
        f'  "management_tone": "<Hawkish|Dovish|Neutral> with 1-sentence justification",\n'
        f'  "forward_guidance": "<1-2 sentence summary of outlook>",\n'
        f'  "capex_and_margins": "<key statements about CAPEX or margins>",\n'
        f'  "qa_highlights": [\n'
        f'    {{"question": "<analyst question>", "response": "<management response>"}},\n'
        f'    {{"question": "<analyst question>", "response": "<management response>"}}\n'
        f'  ],\n'
        f'  "key_risks": "<1-2 risks flagged>",\n'
        f'  "sentiment_shift": "<tone change within the call or across quarters>",\n'
        f'{delta_field}'
        f'}}\n\n'
        f"TRANSCRIPT(S):\n{transcript_block}"
    )

    try:
        import anthropic
        import time

        client = anthropic.Anthropic(api_key=anthropic_api_key)

        for attempt in range(3):
            try:
                resp = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=1500,
                    system="You are a senior Wall Street buy-side equity analyst. Analyze earnings call transcripts with precision. Return only valid JSON.",
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = resp.content[0].text.strip()
                break
            except Exception as e:
                if "overloaded" in str(e).lower() or "529" in str(e):
                    if attempt < 2:
                        time.sleep(3 * (attempt + 1))
                        continue
                raise

        # Parse JSON
        import re as _re
        cleaned = _re.sub(r"<think>.*?</think>", "", raw, flags=_re.DOTALL).strip()

        parsed = None
        try:
            parsed = _json.loads(cleaned)
        except (_json.JSONDecodeError, ValueError):
            brace_start = cleaned.find("{")
            brace_end = cleaned.rfind("}")
            if brace_start != -1 and brace_end > brace_start:
                try:
                    parsed = _json.loads(cleaned[brace_start:brace_end + 1])
                except (_json.JSONDecodeError, ValueError):
                    pass

        if parsed and isinstance(parsed, dict):
            result = {
                "management_tone": parsed.get("management_tone", "N/A"),
                "forward_guidance": parsed.get("forward_guidance", "N/A"),
                "capex_and_margins": parsed.get("capex_and_margins", "N/A"),
                "qa_highlights": parsed.get("qa_highlights", []),
                "key_risks": parsed.get("key_risks", "N/A"),
                "sentiment_shift": parsed.get("sentiment_shift", "N/A"),
                "raw": cleaned,
            }
            # QoQ sentiment deltas (if 2 quarters analyzed)
            deltas = parsed.get("sentiment_deltas", [])
            if deltas and isinstance(deltas, list):
                result["sentiment_deltas"] = deltas
                result["has_qoq"] = True
            else:
                result["sentiment_deltas"] = []
                result["has_qoq"] = False
            return result

        return {"error": "Failed to parse Claude response", "raw": cleaned}

    except ImportError:
        return {"error": "anthropic package not installed"}
    except Exception as e:
        return {"error": f"Claude analysis failed: {e}"}


def fetch_price_targets_fmp(ticker: str, fmp_key: str) -> Dict:
    """
    Fetch analyst price target consensus from FMP.
    API: https://financialmodelingprep.com/api/v4/price-target-consensus?symbol={ticker}
    Returns: {low, median, consensus, high, current_price, num_analysts}
    """
    if not fmp_key:
        return {}
    try:
        url = f"https://financialmodelingprep.com/api/v4/price-target-consensus?symbol={ticker.upper()}&apikey={fmp_key}"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data and isinstance(data, list) and len(data) > 0:
            d = data[0]
            return {
                "low": d.get("targetLow"),
                "median": d.get("targetMedian"),
                "consensus": d.get("targetConsensus"),
                "high": d.get("targetHigh"),
            }
        return {}
    except Exception:
        return {}


# ══════════════════════════════════════════════════════════════
#  Comprehensive Ticker Research
# ══════════════════════════════════════════════════════════════

def fetch_ticker_research(ticker: str, fmp_key: str = "") -> Dict:
    """
    Comprehensive single-ticker research aggregator.
    Fetches fundamentals, valuation, technicals, insider activity,
    analyst ratings, institutional holders, and builds a summary context
    string suitable for LLM-based recommendation generation.

    Each data source is wrapped in try/except so partial failures
    do not break the overall result.

    Returns a single dict with all research data organized by category.
    """
    tk = yf.Ticker(ticker)
    result: Dict = {
        "ticker": ticker.upper(),
        "company_name": None,
        "sector": None,
        "industry": None,
        "description": None,
        "website": None,
        "employees": None,
        "market_cap": None,
        "current_price": None,
        "fundamentals": {},
        "valuation": {},
        "analyst_rating": None,
        "analyst_count": None,
        "price_targets": {},
        "recent_upgrades": [],
        "technicals": {},
        "insider": {},
        "top_institutions": [],
        "institutional_pct": None,
        "summary_context": "",
    }

    # ── 1. yfinance .info (company profile + all useful fields) ──
    info: Dict = {}
    try:
        info = tk.info or {}
        result["company_name"] = info.get("shortName") or info.get("longName")
        result["sector"] = info.get("sector")
        result["industry"] = info.get("industry")
        result["description"] = info.get("longBusinessSummary")
        result["website"] = info.get("website")
        result["employees"] = info.get("fullTimeEmployees")
        result["market_cap"] = info.get("marketCap")
        result["current_price"] = (
            info.get("currentPrice")
            or info.get("regularMarketPrice")
        )
        result["institutional_pct"] = info.get("heldPercentInstitutions")
    except Exception as e:
        logger.warning("ticker_research.info_failed", ticker=ticker, error=str(e))

    # ── 2. Fundamentals via _fetch_single_fundamental ──
    try:
        fund_result = _fetch_single_fundamental(ticker)
        if fund_result is not None:
            _, fund_row = fund_result
            result["fundamentals"] = fund_row
    except Exception as e:
        logger.warning("ticker_research.fundamentals_failed", ticker=ticker, error=str(e))

    # ── 3. Valuation via compute_advanced_dcf ──
    try:
        result["valuation"] = compute_advanced_dcf(ticker)
    except Exception as e:
        logger.warning("ticker_research.dcf_failed", ticker=ticker, error=str(e))

    # ── 4. Insider activity via _fetch_single_insider ──
    try:
        insider_result = _fetch_single_insider(ticker)
        if insider_result is not None:
            _, insider_data = insider_result
            result["insider"] = insider_data
    except Exception as e:
        logger.warning("ticker_research.insider_failed", ticker=ticker, error=str(e))

    # ── 5. Analyst recommendations (latest consensus) ──
    try:
        recs = tk.recommendations
        if recs is not None and not recs.empty:
            # yfinance recommendations DataFrame has columns like
            # period, strongBuy, buy, hold, sell, strongSell
            latest = recs.iloc[-1]
            strong_buy = int(latest.get("strongBuy", 0) or 0)
            buy = int(latest.get("buy", 0) or 0)
            hold = int(latest.get("hold", 0) or 0)
            sell = int(latest.get("sell", 0) or 0)
            strong_sell = int(latest.get("strongSell", 0) or 0)
            total = strong_buy + buy + hold + sell + strong_sell
            result["analyst_count"] = total

            if total > 0:
                # Weighted score: 5=strongBuy .. 1=strongSell
                score = (
                    5 * strong_buy + 4 * buy + 3 * hold
                    + 2 * sell + 1 * strong_sell
                ) / total
                if score >= 4.0:
                    result["analyst_rating"] = "Strong Buy"
                elif score >= 3.5:
                    result["analyst_rating"] = "Buy"
                elif score >= 2.5:
                    result["analyst_rating"] = "Hold"
                elif score >= 1.5:
                    result["analyst_rating"] = "Sell"
                else:
                    result["analyst_rating"] = "Strong Sell"
            else:
                result["analyst_rating"] = "N/A"
    except Exception as e:
        logger.warning("ticker_research.recommendations_failed", ticker=ticker, error=str(e))

    # ── 6. Analyst upgrades / downgrades (recent 5) ──
    try:
        upgrades = tk.upgrades_downgrades
        if upgrades is not None and not upgrades.empty:
            recent = upgrades.head(5)
            upgrade_list = []
            for idx, row in recent.iterrows():
                entry = {
                    "date": str(idx) if not isinstance(idx, int) else None,
                    "firm": row.get("Firm", ""),
                    "to_grade": row.get("ToGrade", ""),
                    "from_grade": row.get("FromGrade", ""),
                    "action": row.get("Action", ""),
                }
                upgrade_list.append(entry)
            result["recent_upgrades"] = upgrade_list
    except Exception as e:
        logger.warning("ticker_research.upgrades_failed", ticker=ticker, error=str(e))

    # ── 7. Price targets from FMP ──
    try:
        if fmp_key:
            pt = fetch_price_targets_fmp(ticker, fmp_key)
            if pt:
                result["price_targets"] = pt
        # Also pull yfinance target prices from info as fallback
        if not result["price_targets"]:
            yf_targets = {}
            if info.get("targetLowPrice"):
                yf_targets["low"] = info["targetLowPrice"]
            if info.get("targetMedianPrice"):
                yf_targets["median"] = info["targetMedianPrice"]
            if info.get("targetMeanPrice"):
                yf_targets["consensus"] = info["targetMeanPrice"]
            if info.get("targetHighPrice"):
                yf_targets["high"] = info["targetHighPrice"]
            if yf_targets:
                result["price_targets"] = yf_targets
    except Exception as e:
        logger.warning("ticker_research.price_targets_failed", ticker=ticker, error=str(e))

    # ── 8. Technicals: RSI(14), SMA50, SMA200, MACD, Bollinger Bands ──
    try:
        hist = tk.history(period="1y")
        if hist is not None and not hist.empty and len(hist) > 50:
            close = hist["Close"]
            current = float(close.iloc[-1])

            # RSI(14)
            delta = close.diff()
            gain = delta.clip(lower=0)
            loss = -delta.clip(upper=0)
            avg_gain = gain.rolling(14).mean()
            avg_loss = loss.rolling(14).mean()
            rs = avg_gain / avg_loss
            rsi_series = 100 - (100 / (1 + rs))
            rsi_val = round(float(rsi_series.dropna().iloc[-1]), 2) if not rsi_series.dropna().empty else None

            # SMA50 & SMA200
            sma50_series = close.rolling(50).mean()
            sma50 = round(float(sma50_series.dropna().iloc[-1]), 2) if not sma50_series.dropna().empty else None

            sma200_series = close.rolling(200).mean()
            sma200 = round(float(sma200_series.dropna().iloc[-1]), 2) if len(close) >= 200 and not sma200_series.dropna().empty else None

            # MACD (12, 26, 9)
            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            macd_line = ema12 - ema26
            macd_signal = macd_line.ewm(span=9, adjust=False).mean()
            macd_val = round(float(macd_line.iloc[-1]), 4)
            macd_sig_val = round(float(macd_signal.iloc[-1]), 4)

            # Bollinger Bands (20, 2)
            bb_sma = close.rolling(20).mean()
            bb_std = close.rolling(20).std()
            bb_upper_series = bb_sma + 2 * bb_std
            bb_lower_series = bb_sma - 2 * bb_std

            bb_upper = round(float(bb_upper_series.dropna().iloc[-1]), 2) if not bb_upper_series.dropna().empty else None
            bb_lower = round(float(bb_lower_series.dropna().iloc[-1]), 2) if not bb_lower_series.dropna().empty else None

            # Bollinger %B = (price - lower) / (upper - lower)
            bb_pct = None
            if bb_upper is not None and bb_lower is not None and bb_upper != bb_lower:
                bb_pct = round((current - bb_lower) / (bb_upper - bb_lower), 4)

            result["technicals"] = {
                "rsi14": rsi_val,
                "sma50": sma50,
                "sma200": sma200,
                "price_vs_sma50": round((current - sma50) / sma50 * 100, 2) if sma50 else None,
                "price_vs_sma200": round((current - sma200) / sma200 * 100, 2) if sma200 else None,
                "macd": macd_val,
                "macd_signal": macd_sig_val,
                "bb_upper": bb_upper,
                "bb_lower": bb_lower,
                "bb_pct": bb_pct,
            }
    except Exception as e:
        logger.warning("ticker_research.technicals_failed", ticker=ticker, error=str(e))

    # ── 9. Institutional holders (top 10) ──
    try:
        inst = tk.institutional_holders
        if inst is not None and not inst.empty:
            top10 = inst.head(10)
            holders_list = []
            for _, row in top10.iterrows():
                holders_list.append({
                    "name": row.get("Holder", ""),
                    "shares": int(row["Shares"]) if pd.notna(row.get("Shares")) else None,
                    "value": float(row["Value"]) if pd.notna(row.get("Value")) else None,
                    "pct_held": float(row["pctHeld"]) if "pctHeld" in row and pd.notna(row.get("pctHeld")) else (
                        float(row["% Out"]) if "% Out" in row and pd.notna(row.get("% Out")) else None
                    ),
                })
            result["top_institutions"] = holders_list
    except Exception as e:
        logger.warning("ticker_research.institutions_failed", ticker=ticker, error=str(e))

    # ── 10. Build summary_context for LLM consumption ──
    try:
        lines = []
        lines.append(f"=== Research Summary for {result['ticker']} ===")
        lines.append(f"Company: {result['company_name'] or 'N/A'}")
        lines.append(f"Sector: {result['sector'] or 'N/A'} | Industry: {result['industry'] or 'N/A'}")
        if result["description"]:
            # Truncate description to first 500 chars for context efficiency
            desc = result["description"][:500]
            lines.append(f"Business: {desc}")
        lines.append(f"Website: {result['website'] or 'N/A'}")
        lines.append(f"Employees: {result['employees']:,}" if result['employees'] else "Employees: N/A")

        mc = result.get("market_cap")
        if mc:
            if mc >= 1e12:
                mc_str = f"${mc/1e12:.2f}T"
            elif mc >= 1e9:
                mc_str = f"${mc/1e9:.2f}B"
            elif mc >= 1e6:
                mc_str = f"${mc/1e6:.1f}M"
            else:
                mc_str = f"${mc:,.0f}"
            lines.append(f"Market Cap: {mc_str}")

        cp = result.get("current_price")
        lines.append(f"Current Price: ${cp:.2f}" if cp else "Current Price: N/A")

        # Fundamentals
        fund = result.get("fundamentals", {})
        if fund:
            lines.append("\n--- Fundamentals ---")
            for key, val in fund.items():
                if val is not None:
                    if isinstance(val, float):
                        if "%" in key or key in ("Div Yield", "Rev Growth", "Earn Growth", "Profit Margin", "ROE", "% from 52W High"):
                            lines.append(f"  {key}: {val:.2%}")
                        else:
                            lines.append(f"  {key}: {val:.2f}")
                    else:
                        lines.append(f"  {key}: {val}")

        # Valuation
        val_data = result.get("valuation", {})
        if val_data and val_data.get("intrinsic_value") is not None:
            lines.append("\n--- Valuation (DCF) ---")
            lines.append(f"  Method: {val_data.get('method', 'N/A')}")
            lines.append(f"  Intrinsic Value: ${val_data['intrinsic_value']:.2f}" if val_data.get('intrinsic_value') else "  Intrinsic Value: N/A")
            lines.append(f"  Upside: {val_data['upside_pct']:.1f}%" if val_data.get('upside_pct') is not None else "  Upside: N/A")
            lines.append(f"  Verdict: {val_data.get('verdict', 'N/A')}")

        # Analyst
        if result.get("analyst_rating"):
            lines.append("\n--- Analyst Consensus ---")
            lines.append(f"  Rating: {result['analyst_rating']} (from {result.get('analyst_count', 'N/A')} analysts)")
        pt = result.get("price_targets", {})
        if pt:
            lines.append(f"  Price Targets: Low=${pt.get('low', 'N/A')}, Median=${pt.get('median', 'N/A')}, Consensus=${pt.get('consensus', 'N/A')}, High=${pt.get('high', 'N/A')}")

        # Upgrades
        upgrades = result.get("recent_upgrades", [])
        if upgrades:
            lines.append("\n--- Recent Upgrades/Downgrades ---")
            for u in upgrades:
                lines.append(f"  {u.get('date', 'N/A')}: {u.get('firm', 'N/A')} - {u.get('action', 'N/A')} to {u.get('to_grade', 'N/A')} (from {u.get('from_grade', 'N/A')})")

        # Technicals
        tech = result.get("technicals", {})
        if tech:
            lines.append("\n--- Technical Indicators ---")
            lines.append(f"  RSI(14): {tech.get('rsi14', 'N/A')}")
            lines.append(f"  SMA50: {tech.get('sma50', 'N/A')} (price {tech.get('price_vs_sma50', 'N/A')}% vs SMA50)")
            lines.append(f"  SMA200: {tech.get('sma200', 'N/A')} (price {tech.get('price_vs_sma200', 'N/A')}% vs SMA200)")
            lines.append(f"  MACD: {tech.get('macd', 'N/A')} | Signal: {tech.get('macd_signal', 'N/A')}")
            lines.append(f"  Bollinger Bands: Upper={tech.get('bb_upper', 'N/A')}, Lower={tech.get('bb_lower', 'N/A')}, %B={tech.get('bb_pct', 'N/A')}")

        # Insider
        ins = result.get("insider", {})
        if ins:
            lines.append("\n--- Insider Activity (90d) ---")
            lines.append(f"  Direction: {ins.get('direction', 'N/A')} | Net Shares: {ins.get('net_shares', 0):,} | Txn Count: {ins.get('count', 0)}")
            for txn in ins.get("recent_txns", []):
                lines.append(f"    - {txn}")

        # Institutional
        inst_pct = result.get("institutional_pct")
        if inst_pct is not None:
            lines.append(f"\n--- Institutional Ownership: {inst_pct:.1%} ---")
        top_inst = result.get("top_institutions", [])
        if top_inst:
            for h in top_inst[:5]:
                shares_str = f"{h['shares']:,}" if h.get('shares') else 'N/A'
                lines.append(f"  {h.get('name', 'N/A')}: {shares_str} shares")

        result["summary_context"] = "\n".join(lines)
    except Exception as e:
        logger.warning("ticker_research.summary_context_failed", ticker=ticker, error=str(e))
        result["summary_context"] = f"Research data for {ticker} (summary generation failed)"

    return result