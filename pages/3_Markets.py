"""
pages/3_Markets.py
External Context: What is happening in markets and with my holdings?
"""

import os
import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from app import (get_sector, SECTOR_MAP, CLR_ACCENT, CLR_WARN,
                 CLR_DANGER, CLR_GOOD, CLR_MUTED, CLR_GRID, CLR_GOLD,
                 call_llm, fetch_asset_news, score_sentiment_ollama,
                 score_reddit_fomo, build_risk_context,
                 render_sentiment_tear_sheet, _safe_get_secret)
from i18n import get_translator
from ui.components import render_section, render_chart, render_metric_list, render_empty_state
from market_intelligence import (
    get_vix_current, fetch_vix_data, fetch_yield_curve, fetch_fear_greed,
    get_all_macro_news, fetch_fundamentals, format_fundamentals_for_display,
    fetch_reddit_sentiment_apify, format_reddit_for_llm,
)

# Render shared sidebar
from ui.shared_sidebar import render_shared_sidebar
render_shared_sidebar()

# ── Guard ────────────────────────────────────────────────────
if not st.session_state.get("analysis_ready"):
    _lang = st.session_state.get("_lang", "en")
    render_empty_state(
        title="Markets need a portfolio to contextualize" if _lang == "en" else "市场页面需要组合数据",
        description=(
            "VIX, Fear & Greed, yield curve, macro news, AI sentiment and earnings call AI. "
            "Sentiment scoring uses your holdings — run analysis to start."
            if _lang == "en" else
            "VIX、恐贪指数、收益率曲线、宏观新闻、AI 情绪分析、财报电话会 AI。"
            "情绪分析基于你的持仓 — 请先运行分析。"
        ),
        action_hint="Crypto + equity coverage · ~30 tickers scored per run"
                   if _lang == "en" else "覆盖加密货币 + 股票 · 每次约 30 只",
    )
    st.stop()

lang = st.session_state.get("_lang", "en")
t = get_translator(lang)
report = st.session_state.get("report")
weights = st.session_state.get("weights")
prices = st.session_state.get("prices")
mc_horizon = st.session_state.get("mc_horizon")
market_shock = st.session_state.get("market_shock")
model_provider = st.session_state.get("_model_provider", "Ollama (Local)")
api_key_input = st.session_state.get("_api_key_input", "")
deepseek_key = st.session_state.get("_deepseek_key", "")
ollama_model = st.session_state.get("_ollama_model", "deepseek-r1:14b")



# ══════════════════════════════════════════════════════════════
#  1. Market Regime Strip — VIX + F&G + Yield Curve (3 compact cards)
# ══════════════════════════════════════════════════════════════
render_section("Market Regime" if lang == "en" else "市场状态")

# Auto-load market regime data on first visit (cached for the session).
# Avoids the "click button or see --" dead state.
_needs_regime_load = not all(
    st.session_state.get(k) is not None
    for k in ("vix_current", "fear_greed_data", "yield_analysis")
)

load_col, refresh_col, _ = st.columns([1, 1, 2])
with load_col:
    run_regime = st.button(
        "Refresh Market Data" if lang == "en" else "刷新市场数据",
        type="primary", key="run_regime", use_container_width=True,
    )
with refresh_col:
    if _needs_regime_load:
        st.caption("Auto-loading…" if lang == "en" else "首次加载中…")

if run_regime or _needs_regime_load:
    with st.spinner("Fetching VIX, Fear & Greed, Yield Curve..." if lang == "en" else "正在获取 VIX / 恐贪指数 / 收益率曲线..."):
        try:
            st.session_state.vix_current = get_vix_current()
        except Exception as e:
            st.warning(f"VIX fetch failed: {e}" if lang == "en" else f"VIX 获取失败: {e}")
            st.session_state.vix_current = None
        try:
            st.session_state.vix_hist = fetch_vix_data(period="1y")
        except Exception:
            st.session_state.vix_hist = None
        try:
            yc_df, yc_analysis = fetch_yield_curve()
            st.session_state.yield_curve_df = yc_df
            st.session_state.yield_analysis = yc_analysis
        except Exception as e:
            st.warning(f"Yield curve fetch failed: {e}" if lang == "en" else f"收益率曲线获取失败: {e}")
        try:
            st.session_state.fear_greed_data = fetch_fear_greed()
        except Exception as e:
            st.warning(f"Fear & Greed fetch failed: {e}" if lang == "en" else f"恐贪指数获取失败: {e}")

vix_cur = st.session_state.get("vix_current")
fg_data = st.session_state.get("fear_greed_data")
yc_analysis = st.session_state.get("yield_analysis")

rc1, rc2, rc3 = st.columns(3)
with rc1:
    if vix_cur and vix_cur.get("current") is not None:
        v_val = vix_cur["current"]
        st.metric(f"{vix_cur.get('level_icon', '')} VIX", f"{v_val:.2f}",
                  delta=f"{vix_cur.get('change', 0):+.1%}" if vix_cur.get("change") else None,
                  delta_color="inverse")
    else:
        st.metric("VIX", "-- (Load data)")

with rc2:
    if fg_data and fg_data.get("score") is not None:
        fg_score = fg_data["score"]
        fg_rating = fg_data.get("rating_display", "N/A")
        st.metric(f"Fear & Greed", f"{fg_score}/100 -- {fg_rating}")
    else:
        st.metric("Fear & Greed", "-- (Load data)")

with rc3:
    if yc_analysis:
        status = yc_analysis.get("curve_status", "N/A")
        icon = yc_analysis.get("curve_icon", "")
        spread = yc_analysis.get("3M-10Y Spread")
        spread_str = f"{spread:+.2f}%" if spread is not None else ""
        st.metric(f"{icon} Yield Curve", f"{status} {spread_str}")
    else:
        st.metric("Yield Curve", "-- (Load data)")

# ── Yield curve visualization (current vs 30d ago vs 90d ago) ──
_yc_df = st.session_state.get("yield_curve_df")
if _yc_df is not None and not _yc_df.empty:
    fig_yc = go.Figure()
    fig_yc.add_trace(go.Scatter(
        x=_yc_df["Maturity"], y=_yc_df["Current (%)"],
        mode="lines+markers", name="Current",
        line=dict(color="#0B7285", width=3), marker=dict(size=8),
    ))
    fig_yc.add_trace(go.Scatter(
        x=_yc_df["Maturity"], y=_yc_df["30d Ago (%)"],
        mode="lines+markers", name="30 days ago",
        line=dict(color="#8B949E", width=2, dash="dash"), marker=dict(size=6),
    ))
    fig_yc.add_trace(go.Scatter(
        x=_yc_df["Maturity"], y=_yc_df["90d Ago (%)"],
        mode="lines+markers", name="90 days ago",
        line=dict(color="#484F58", width=1, dash="dot"), marker=dict(size=5),
    ))
    fig_yc.update_layout(
        title="US Treasury Yield Curve" if lang == "en" else "美国国债收益率曲线",
        xaxis_title="Maturity" if lang == "en" else "期限",
        yaxis_title="Yield (%)" if lang == "en" else "收益率 (%)",
        height=320,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    render_chart(fig_yc)


# ══════════════════════════════════════════════════════════════
#  2. Macro News Feed (compact, 8 items max)
# ══════════════════════════════════════════════════════════════
render_section(t("macro_news_title"))

mnews_col, _ = st.columns([1, 3])
with mnews_col:
    run_mnews = st.button(t("macro_news_btn"), type="primary", key="run_macro_news", use_container_width=True)

if run_mnews:
    with st.spinner(t("macro_news_spinner")):
        st.session_state.macro_news_data = get_all_macro_news(max_items=30)

mnews_data = st.session_state.get("macro_news_data")
if mnews_data:
    for i, item in enumerate(mnews_data[:8]):
        source_badge = f"`{item['source']}`"
        title = item["title"]
        link = item.get("link", "")
        title_md = f"[{title}]({link})" if link else title
        st.markdown(f"{source_badge} {title_md}")
        if i < 7:
            st.markdown("<hr style='margin:2px 0;opacity:0.1'>", unsafe_allow_html=True)
    if len(mnews_data) > 8:
        with render_section(f"View all {len(mnews_data)} items", collapsed=True):
            for i, item in enumerate(mnews_data[8:], start=9):
                st.markdown(f"`{item['source']}` {item['title']}")


# ══════════════════════════════════════════════════════════════
#  3. Ticker Research Quick Access
# ══════════════════════════════════════════════════════════════
st.markdown("---")
render_section("Ticker Research" if lang == "en" else "个股研究")

st.markdown(
    '<div style="background:rgba(11,114,133,0.08);border:1px solid rgba(11,114,133,0.2);'
    'border-radius:8px;padding:16px 20px;margin:8px 0">'
    '<div style="font-size:14px;font-weight:600;color:#E6EDF3;margin-bottom:6px">'
    f'{"For comprehensive single-stock analysis (fundamentals, valuation, technicals, insider activity, analyst ratings, AI recommendation), use the" if lang == "en" else "如需全面的个股分析（基本面、估值、技术面、内部人交易、分析师评级、AI推荐），请使用"}'
    f' <b>{"Ticker Research" if lang == "en" else "个股研究"}</b> '
    f'{"page in the sidebar." if lang == "en" else "页面（侧边栏）。"}'
    '</div>'
    '<div style="font-size:12px;color:#8B949E">'
    f'{"Supports any ticker symbol — not limited to your portfolio holdings." if lang == "en" else "支持搜索任意股票代码，不限于持仓股票。"}'
    '</div>'
    '</div>',
    unsafe_allow_html=True,
)

# ── Ticker selector for Sentiment / Earnings sections below ──
# Show ALL holdings (sorted by weight), not just top 10.
# Crypto filtered out of equity-centric sections but user can still search.
all_tickers_sorted = sorted(weights, key=lambda x: -weights[x])
equity_tickers = [tk for tk in all_tickers_sorted if not tk.endswith("-USD")]
selector_options = equity_tickers if equity_tickers else all_tickers_sorted
selected_ticker = st.selectbox(
    "Select Ticker" if lang == "en" else "选择股票",
    selector_options,
    key="market_intel_ticker",
    help=(
        f"Choose from all {len(selector_options)} equity holdings"
        if lang == "en" else
        f"从全部 {len(selector_options)} 只股票持仓中选择"
    ),
)


# ══════════════════════════════════════════════════════════════
#  5. Sentiment Tear Sheet for selected ticker
# ══════════════════════════════════════════════════════════════
st.markdown("---")
render_section("AI Sentiment" if lang == "en" else "AI 情绪分析")

_llm_available = (
    (model_provider == "Anthropic Claude" and api_key_input) or
    (model_provider == "DeepSeek API" and deepseek_key) or
    model_provider == "Ollama (Local)"
)

if not _llm_available:
    st.info(t("sentiment_need_ollama"))
else:
    # Universe = ALL portfolio holdings (stocks via yfinance + crypto via CryptoPanic).
    _all_by_weight = sorted(weights.keys(), key=lambda x: -weights[x])
    _equity_by_weight = [tk for tk in _all_by_weight if not tk.endswith("-USD")]
    _total_holdings = len(_all_by_weight)

    info_col, sent_col, reddit_col = st.columns([2, 1, 1])
    with info_col:
        st.caption(
            f"Will analyze all {_total_holdings} holdings "
            f"({len(_equity_by_weight)} equities + {_total_holdings - len(_equity_by_weight)} crypto). "
            f"Each click fetches fresh news."
            if lang == "en" else
            f"将分析全部 {_total_holdings} 只持仓（{len(_equity_by_weight)} 股票 + "
            f"{_total_holdings - len(_equity_by_weight)} 加密）。每次点击获取最新新闻。"
        )
    with sent_col:
        run_sent = st.button(t("sentiment_btn"), type="primary", key="run_sentiment", use_container_width=True)
    with reddit_col:
        _apify_key = os.environ.get("APIFY_API_KEY", "") or _safe_get_secret("APIFY_API_KEY")
        run_reddit = st.button(
            "Reddit FOMO" if lang == "en" else "Reddit 散户情绪",
            key="run_reddit", use_container_width=True,
            help="Reddit sentiment covers equities + crypto via r/wallstreetbets and r/stocks"
                 if lang == "en" else
                 "Reddit 情绪覆盖股票 + 加密货币，来源 r/wallstreetbets + r/stocks",
        )

    if run_sent:
        # Always fresh — clear the 60s cache for just this call's tickers.
        try:
            fetch_asset_news.clear()
        except Exception:
            pass
        selected = _all_by_weight  # ALL holdings
        progress_bar = st.progress(0, text=f"Fetching news for {len(selected)} tickers...")
        news_data = fetch_asset_news(tuple(selected))

        # Parallelize LLM scoring — each call is ~2-5s; serial means 10 tickers
        # takes 30s+. ThreadPoolExecutor cuts that to ~6-8s. Cap workers at 5
        # to avoid tripping provider rate limits (Claude/DeepSeek) or local
        # Ollama's single-GPU bottleneck.
        from concurrent.futures import ThreadPoolExecutor, as_completed
        sentiment_results: dict = {}
        completed = 0
        with st.spinner(f"Scoring {len(selected)} tickers in parallel (max 5 at once)..."):
            with ThreadPoolExecutor(max_workers=5) as ex:
                future_to_tk = {
                    ex.submit(score_sentiment_ollama, tk, news_data.get(tk, []), ollama_model): tk
                    for tk in selected
                }
                for fut in as_completed(future_to_tk):
                    tk = future_to_tk[fut]
                    try:
                        scored = fut.result()
                    except Exception as e:
                        scored = {
                            "retail_sentiment_score": 5.0, "sentiment_label": "Error",
                            "key_narrative": f"Scoring failed: {e}",
                            "score": 5, "confidence": "Low",
                        }
                    scored["headlines"] = news_data.get(tk, [])
                    scored["weight"] = weights[tk]
                    sentiment_results[tk] = scored
                    completed += 1
                    progress_bar.progress(completed / len(selected),
                                          text=f"Scored {completed}/{len(selected)}")
        progress_bar.empty()

        st.session_state.sentiment_data = sentiment_results
        st.session_state.sentiment_last_run = datetime.now() if False else __import__("time").time()
        st.session_state.risk_context = build_risk_context(
            report, weights, mc_horizon, market_shock, prices,
            sentiment=sentiment_results,
            fund_data=st.session_state.get("fundamentals_data"),
            insider_data=st.session_state.get("insider_data"),
            technical_data=st.session_state.get("technical_data"),
        )

    # Reddit FOMO — scores ALL holdings (ticker matching via word-boundary regex)
    if run_reddit:
        selected_reddit = _all_by_weight
        with st.spinner(f"Scraping Reddit for {len(selected_reddit)} tickers..."):
            reddit_data = fetch_reddit_sentiment_apify(selected_reddit, max_posts=12, apify_key=_apify_key)
            hot_posts = reddit_data.get("_hot", [])
            hot_text = format_reddit_for_llm(hot_posts)
            fomo_results = {"_hot_posts": hot_posts}
            for tk in selected_reddit:
                tk_posts = reddit_data.get(tk, [])
                if tk_posts:
                    # Real ticker-specific posts exist — score with them
                    combined_text = format_reddit_for_llm(tk_posts)
                    fomo = score_reddit_fomo(tk, combined_text)
                    fomo["posts"] = tk_posts
                    fomo["data_source"] = f"ticker-specific ({len(tk_posts)} posts)"
                else:
                    # No mentions — don't score generic hot posts (produced identical scores).
                    # Mark as "no data" so UI can skip or flag it.
                    fomo = {
                        "fomo_score": None,
                        "retail_consensus": "No Reddit mentions in last 24h",
                        "posts": [],
                        "data_source": "no_mentions",
                    }
                fomo_results[tk] = fomo
            st.session_state.reddit_fomo_data = fomo_results

    sent = st.session_state.get("sentiment_data")

    # Score overview bar chart — primary view: ALL holdings at a glance.
    # Individual tear sheet moved below as a drill-down.
    if sent:
        st.markdown("")
        sent_df = pd.DataFrame([
            {"Ticker": tk, "Score": d.get("retail_sentiment_score", d.get("score", 5))}
            for tk, d in sorted(sent.items(), key=lambda x: x[1].get("retail_sentiment_score", x[1].get("score", 5)))
        ])
        bar_colors_sent = [CLR_DANGER if s <= 3 else (CLR_WARN if s < 5 else CLR_GOOD) for s in sent_df["Score"]]
        fig_sent = go.Figure(go.Bar(
            x=sent_df["Ticker"], y=sent_df["Score"],
            marker_color=bar_colors_sent,
            text=sent_df["Score"].map(lambda s: f"{s:.1f}"),
            textposition="outside",
        ))
        fig_sent.add_hline(y=7, line_dash="dot", line_color=CLR_GOOD, opacity=0.4)
        fig_sent.add_hline(y=3, line_dash="dot", line_color=CLR_DANGER, opacity=0.4)
        fig_sent.update_layout(title="Sentiment Score Overview", yaxis=dict(range=[0, 11]), height=300)
        render_chart(fig_sent)

        # ── Full overview table: weight + score + top headline ─────
        st.markdown("")
        render_section(
            "All Holdings — Sentiment & Headlines"
            if lang == "en" else
            "全持仓情绪与头条"
        )
        _rows = []
        for tk in sorted(sent.keys(), key=lambda x: -weights.get(x, 0)):
            d = sent[tk]
            score = d.get("retail_sentiment_score", d.get("score", None))
            label = d.get("sentiment_label", "")
            headlines = d.get("headlines", []) or []
            top_headline = headlines[0] if headlines else "(no news)"
            confidence = d.get("confidence", "--")
            _rows.append({
                "Ticker": tk,
                "Weight": f"{weights.get(tk, 0) * 100:.1f}%",
                "Score": f"{score:.1f}" if isinstance(score, (int, float)) else "--",
                "Label": label or "--",
                "Confidence": confidence,
                "News": len(headlines),
                "Top Headline": top_headline[:120],
            })
        st.dataframe(
            pd.DataFrame(_rows),
            use_container_width=True,
            hide_index=True,
            height=min(400, 40 + 35 * len(_rows)),
        )

        # ── Drill-down tear sheet for selected ticker ──────────────
        # The selector above the sentiment table lets users deep-dive one
        # holding; the table above is the primary cross-portfolio view.
        if selected_ticker in sent:
            st.markdown("")
            render_section(
                f"Detail — {selected_ticker}" if lang == "en" else f"明细 — {selected_ticker}",
                collapsed=True,
            )
            render_sentiment_tear_sheet(
                selected_ticker, sent[selected_ticker],
                sent[selected_ticker].get("weight", weights.get(selected_ticker, 0)), lang,
            )


# Earnings Call AI used to live here; it now lives (as the full Institutional
# Analyst Report) on the Ticker Research page alongside fundamentals, peer
# comps, and analyst ratings. Keeping it here duplicated work and split the
# data flow across two pages.


# ══════════════════════════════════════════════════════════════
#  6. Reddit FOMO Panel (Expander)
# ══════════════════════════════════════════════════════════════
reddit_fomo = st.session_state.get("reddit_fomo_data")
if reddit_fomo:
    with render_section("Reddit FOMO Monitor" if lang == "en" else "Reddit 散户情绪监控", collapsed=True):
        # Split scored vs no-mention tickers.
        # A scored ticker has a numeric fomo_score (not None).
        all_tickers = {k: v for k, v in reddit_fomo.items() if k != "_hot_posts" and isinstance(v, dict)}
        scored = {k: v for k, v in all_tickers.items() if v.get("fomo_score") is not None}
        no_mention = [k for k, v in all_tickers.items() if v.get("fomo_score") is None]

        st.caption(
            f"{len(scored)} tickers had Reddit mentions in the last 24h · "
            f"{len(no_mention)} had no mentions"
            if lang == "en" else
            f"{len(scored)} 只在过去 24h 有 Reddit 讨论 · {len(no_mention)} 只无讨论"
        )

        if scored:
            # Show scored tickers (sorted by weight) as cards
            scored_sorted = sorted(scored.items(), key=lambda kv: -weights.get(kv[0], 0))
            for row_start in range(0, len(scored_sorted), 5):
                row_items = scored_sorted[row_start: row_start + 5]
                fomo_cols = st.columns(5)
                for col, (tk, fomo) in zip(fomo_cols, row_items):
                    score = fomo["fomo_score"]
                    fomo_color = CLR_DANGER if score >= 70 else (CLR_GOOD if score <= 30 else CLR_WARN)
                    fomo_label = "FOMO" if score >= 70 else ("Fear" if score <= 30 else "Neutral")
                    post_count = len(fomo.get("posts", []))
                    with col:
                        st.markdown(
                            f'<div style="text-align:center;padding:12px;border-radius:10px;border:2px solid {fomo_color}">'
                            f'<div style="font-size:11px;font-weight:700;opacity:0.5">{tk}</div>'
                            f'<div style="font-size:36px;font-weight:900;color:{fomo_color}">{score}</div>'
                            f'<div style="font-size:12px;font-weight:600;color:{fomo_color}">{fomo_label}</div>'
                            f'<div style="font-size:10px;opacity:0.6;margin-top:4px">{post_count} posts</div>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
                        consensus = fomo.get("retail_consensus", "")
                        if consensus and consensus not in ("No Reddit data", "N/A"):
                            st.caption(consensus[:100])

            # Detailed post text per ticker
            with render_section(
                "Top posts per ticker" if lang == "en" else "每只股票的热门帖子",
                collapsed=True,
            ):
                for tk, fomo in scored_sorted[:10]:
                    posts = fomo.get("posts", [])[:3]
                    if not posts:
                        continue
                    st.markdown(f"**{tk}** · score {fomo['fomo_score']}")
                    for p in posts:
                        st.markdown(
                            f"- `[r/{p.get('subreddit','?')}]` {p.get('title','')} "
                            f"[+{p.get('upvotes', 0)} / {p.get('comments', 0)}c]"
                        )
                    st.markdown("")

        if no_mention:
            st.caption(
                f"No Reddit mentions: {', '.join(no_mention[:15])}"
                f"{'…' if len(no_mention) > 15 else ''}"
                if lang == "en" else
                f"无 Reddit 讨论: {', '.join(no_mention[:15])}"
                f"{'…' if len(no_mention) > 15 else ''}"
            )


# ══════════════════════════════════════════════════════════════
#  8. Full Fundamentals Table (Expander)
# ══════════════════════════════════════════════════════════════
fund_data = st.session_state.get("fundamentals_data")
if fund_data is not None and not fund_data.empty:
    with render_section("Full Fundamentals Table" if lang == "en" else "完整基本面数据", collapsed=True):
        order = [tk for tk in sorted(weights, key=lambda x: -weights[x]) if tk in fund_data.index]
        fund_sorted = fund_data.loc[order].copy()
        fund_sorted.insert(0, "Weight", [f"{weights.get(tk, 0):.1%}" for tk in fund_sorted.index])
        display_df = format_fundamentals_for_display(fund_sorted)
        st.dataframe(display_df, use_container_width=True, height=500)

# Floating AI Assistant
try:
    from ui.floating_chat import render_floating_ai_chat
    render_floating_ai_chat()
except Exception as e:
    pass  # Silently fail if floating chat has issues
