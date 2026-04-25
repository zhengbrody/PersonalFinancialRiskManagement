"""
pages/8_Institutions.py
Institutional Flow & Smart Money -- Wall Street Research Terminal
------------------------------------------------------------------
Bloomberg / Optiver-inspired dark terminal for tracking institutional
positioning, 13F filings, and options flow intelligence.

REFACTORED: All raw HTML tables/grids replaced with Streamlit-native components
(st.dataframe, st.columns, st.metric, render_kpi_row) for reliable rendering.
"""

from datetime import datetime

import pandas as pd
import streamlit as st

from app import call_llm
from i18n import get_translator
from ui.components import render_ai_digest, render_kpi_row, render_section
from ui.shared_sidebar import render_shared_sidebar

# ── Shared sidebar ────────────────────────────────────────────
render_shared_sidebar()

lang = st.session_state.get("_lang", "en")
t = get_translator(lang)


# ══════════════════════════════════════════════════════════════
#  Wall Street Terminal CSS (simple styling only -- no tables)
# ══════════════════════════════════════════════════════════════

st.markdown(
    """
<style>
/* ── Terminal header bar ───────────────────────────────── */
.terminal-header {
    background: linear-gradient(135deg, #0a0e14 0%, #111820 100%);
    border: 1px solid rgba(46, 160, 67, 0.15);
    border-radius: 6px;
    padding: 18px 24px;
    margin-bottom: 20px;
}
.terminal-header .title {
    font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
    font-size: 18px;
    font-weight: 700;
    color: #2EA043;
    letter-spacing: 1.5px;
    text-transform: uppercase;
}
.terminal-header .subtitle {
    font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
    font-size: 11px;
    color: #8B949E;
    letter-spacing: 0.5px;
}
.terminal-header .timestamp {
    font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
    font-size: 11px;
    color: #484F58;
    margin-top: 4px;
}
</style>
""",
    unsafe_allow_html=True,
)


# ══════════════════════════════════════════════════════════════
#  Helper: portfolio tickers
# ══════════════════════════════════════════════════════════════


def _get_portfolio_tickers():
    """Return portfolio tickers from session state or sensible defaults."""
    weights = st.session_state.get("weights")
    if weights:
        return sorted(weights.keys())
    # Try parsing the JSON text input
    import json

    try:
        raw = st.session_state.get("weights_input") or st.session_state.get("weights_json", "{}")
        parsed = json.loads(raw)
        if parsed:
            return sorted(parsed.keys())
    except Exception:
        pass
    return ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA"]


def _badge_text(signal: str) -> str:
    """Return a text label for a conviction/change signal."""
    mapping = {
        "HIGH_CONVICTION": "HIGH",
        "MODERATE": "MOD",
        "LOW": "LOW",
        "NEW": "NEW",
        "INCREASED": "+INC",
        "DECREASED": "-DEC",
        "EXITED": "EXIT",
        "BULLISH": "BULL",
        "BEARISH": "BEAR",
        "NEUTRAL": "NTRL",
        "STRONGLY_BULLISH": "BULL+",
        "STRONGLY_BEARISH": "BEAR-",
        "NO_DATA": "N/A",
        "ERROR": "ERR",
    }
    return mapping.get(signal, signal)


def _signal_emoji(signal: str) -> str:
    """Return emoji indicator for signal."""
    s = signal.upper() if signal else ""
    if s in ("HIGH_CONVICTION", "NEW", "INCREASED", "BULLISH", "STRONGLY_BULLISH"):
        return "\U0001f7e2"  # green circle
    if s in ("LOW", "EXITED", "DECREASED", "BEARISH", "STRONGLY_BEARISH", "ERROR"):
        return "\U0001f534"  # red circle
    if s in ("MODERATE",):
        return "\U0001f7e1"  # yellow circle
    return "\u26aa"  # white circle


def _fmt_number(val, decimals=0):
    """Format a number with commas, monospace-friendly."""
    if val is None:
        return "--"
    try:
        if decimals == 0:
            return f"{int(val):,}"
        return f"{val:,.{decimals}f}"
    except (ValueError, TypeError):
        return "--"


def _fmt_dollars(val, millions=False):
    """Format a dollar value."""
    if val is None:
        return "--"
    try:
        if millions:
            return f"${val / 1_000_000:,.1f}M"
        return f"${val:,.0f}"
    except (ValueError, TypeError):
        return "--"


def _fmt_pct(val, show_sign=True):
    """Format a percentage value."""
    if val is None:
        return "--"
    try:
        prefix = "+" if show_sign and val > 0 else ""
        return f"{prefix}{val:.1f}%"
    except (ValueError, TypeError):
        return "--"


# ══════════════════════════════════════════════════════════════
#  Terminal Header
# ══════════════════════════════════════════════════════════════

now_str = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
st.markdown(
    f"""
<div class="terminal-header">
    <div class="title">INSTITUTIONAL FLOW & SMART MONEY</div>
    <div class="subtitle">SEC 13F Filings  |  Options Flow Intelligence  |  Smart Money Tracking</div>
    <div class="timestamp">LIVE  {now_str}</div>
</div>
""",
    unsafe_allow_html=True,
)

# ── AI Institutional Summary ──
if st.session_state.get("analysis_ready") and st.session_state.get("smart_money_data"):
    try:
        smd = st.session_state.get("smart_money_data")
        high_conviction = [s for s in smd if s.get("signal") == "HIGH_CONVICTION"]
        prompt = f"""As an institutional flow analyst, summarize the smart money positioning (2-3 sentences):
- {len(smd)} holdings tracked across top institutions
- {len(high_conviction)} have HIGH conviction (>20 institutions holding)
- High conviction names: {', '.join(s['ticker'] for s in high_conviction[:5])}
What does this institutional crowding tell us about risk? Plain text only."""
        if lang == "zh":
            prompt += "\n请用中文回答。"
        with st.spinner("..."):
            digest = call_llm(prompt, max_tokens=250, temperature=0.2)
        render_ai_digest(digest, sources="SEC 13F Filings")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════
#  Tabs
# ══════════════════════════════════════════════════════════════

tab_smart, tab_deepdive, tab_options = st.tabs(
    [
        "Smart Money Dashboard",
        "Institution Deep Dive",
        "Options Flow",
    ]
)

portfolio_tickers = _get_portfolio_tickers()


# ══════════════════════════════════════════════════════════════
#  TAB 1: Smart Money Dashboard
# ══════════════════════════════════════════════════════════════

with tab_smart:
    render_section(
        "Smart Money Signals",
        subtitle="Institutional conviction analysis for your portfolio holdings (SEC 13F)",
    )

    try:
        with st.spinner("Scanning institutional 13F filings via SEC EDGAR..."):
            from institutional_tracker import get_smart_money_signals

            signals = get_smart_money_signals(portfolio_tickers)

        # Store for AI digest at top of page
        st.session_state["smart_money_data"] = signals

        if not signals:
            st.info(
                "No institutional signal data available. "
                "13F filings are updated quarterly -- data may not yet be cached. "
                "Try refreshing or check back later."
            )
        else:
            # Summary strip using render_kpi_row
            total = len(signals)
            high_ct = sum(1 for s in signals if s["signal"] == "HIGH_CONVICTION")
            mod_ct = sum(1 for s in signals if s["signal"] == "MODERATE")
            low_ct = sum(1 for s in signals if s["signal"] == "LOW")

            render_kpi_row(
                [
                    {"label": "Total Holdings", "value": str(total)},
                    {"label": "High Conviction", "value": str(high_ct), "delta_color": "positive"},
                    {"label": "Moderate", "value": str(mod_ct), "delta_color": "neutral"},
                    {"label": "Low", "value": str(low_ct), "delta_color": "negative"},
                ]
            )

            # Sort by conviction descending (HIGH first)
            conviction_order = {"HIGH_CONVICTION": 0, "MODERATE": 1, "LOW": 2}
            signals_sorted = sorted(
                signals,
                key=lambda s: (conviction_order.get(s["signal"], 99), -s["num_institutions"]),
            )

            # Build dataframe for display
            table_rows = []
            for s in signals_sorted:
                top_holders_str = ", ".join(s.get("top_holders", [])[:3])
                if len(s.get("top_holders", [])) > 3:
                    top_holders_str += f" +{len(s['top_holders']) - 3} more"

                crowding_pct = f"{s['crowding_score'] * 100:.0f}%"

                table_rows.append(
                    {
                        "Ticker": s["ticker"],
                        "# Institutions": s["num_institutions"],
                        "Crowding": crowding_pct,
                        "Top Holders": top_holders_str,
                        "Conviction": f"{_signal_emoji(s['signal'])} {_badge_text(s['signal'])}",
                    }
                )

            st.dataframe(
                pd.DataFrame(table_rows),
                hide_index=True,
                use_container_width=True,
            )

            # Legend
            st.caption(
                "Conviction thresholds: HIGH = >10 of top 30 funds hold | "
                "MODERATE = 5-10 | LOW = <5.  "
                "Crowding = % of tracked institutions holding the stock.  "
                "Source: SEC EDGAR 13F filings (quarterly, cached 24h)."
            )

    except Exception as exc:
        st.error(f"Failed to load smart money signals: {exc}")
        st.caption("Ensure SEC EDGAR is reachable. 13F data is fetched from data.sec.gov.")


# ══════════════════════════════════════════════════════════════
#  TAB 2: Institution Deep Dive
# ══════════════════════════════════════════════════════════════

with tab_deepdive:
    render_section(
        "Institution Deep Dive",
        subtitle="Explore 13F holdings and QoQ position changes for top institutional filers",
    )

    try:
        from institutional_tracker import (
            fetch_13f_holdings,
            get_institutional_changes,
            get_top_institutions,
        )

        institutions = get_top_institutions()
        inst_names = [inst["name"] for inst in institutions]

        selected_name = st.selectbox(
            "Select Institution",
            inst_names,
            key="inst_deepdive_select",
        )

        # Find CIK for selected institution
        selected_inst = next((i for i in institutions if i["name"] == selected_name), None)

        if selected_inst is None:
            st.info("Institution not found.")
        else:
            cik = selected_inst["cik"]

            # Fetch holdings and changes
            with st.spinner(f"Fetching 13F filing for {selected_name} from SEC EDGAR..."):
                filings_data = fetch_13f_holdings(cik, limit=2)
                changes_data = get_institutional_changes(cik)

            if not filings_data or not filings_data[0].get("holdings"):
                st.info(
                    f"No 13F holdings data available for {selected_name}. "
                    "The filing may not be cached yet, or this institution may not "
                    "have a recent 13F on file with the SEC."
                )
            else:
                filing = filings_data[0]
                holdings = filing["holdings"]
                filing_date = filing.get("filing_date", "Unknown")

                # Portfolio total for % calculation
                total_portfolio_value = sum(h["value"] for h in holdings)

                # Build change lookup from changes_data
                change_lookup = {}
                if changes_data:
                    for pos in changes_data.get("new_positions", []):
                        change_lookup[pos["ticker"]] = ("NEW", None)
                    for pos in changes_data.get("increased", []):
                        change_lookup[pos["ticker"]] = ("INCREASED", pos.get("change_pct", 0))
                    for pos in changes_data.get("decreased", []):
                        change_lookup[pos["ticker"]] = ("DECREASED", pos.get("change_pct", 0))
                    for pos in changes_data.get("exited", []):
                        change_lookup[pos["ticker"]] = ("EXITED", None)

                # Summary KPIs
                summary = changes_data.get("summary", {}) if changes_data else {}
                prev_date = changes_data.get("previous_filing_date", "--") if changes_data else "--"

                render_kpi_row(
                    [
                        {"label": "Total Positions", "value": str(len(holdings))},
                        {
                            "label": "AUM (13F)",
                            "value": _fmt_dollars(total_portfolio_value, millions=True),
                        },
                        {
                            "label": "New Positions",
                            "value": str(summary.get("total_new", 0)),
                            "delta_color": "positive",
                        },
                        {
                            "label": "Exited",
                            "value": str(summary.get("total_exited", 0)),
                            "delta_color": "negative",
                        },
                    ]
                )

                st.caption(
                    f"Filing Date: {filing_date}  |  "
                    f"Previous Filing: {prev_date}  |  "
                    f"Source: SEC EDGAR 13F-HR"
                )

                # Sort holdings by value descending
                holdings_sorted = sorted(holdings, key=lambda h: h["value"], reverse=True)

                # Build holdings dataframe
                holdings_rows = []
                for h in holdings_sorted:
                    ticker = h["ticker"]
                    name = h.get("name", "")
                    shares = h["shares"]
                    value = h["value"]
                    pct_port = (
                        (value / total_portfolio_value * 100) if total_portfolio_value > 0 else 0
                    )

                    # QoQ change
                    change_type, change_pct = change_lookup.get(ticker, (None, None))

                    if change_type == "NEW":
                        qoq_str = "\U0001f7e2 NEW"
                    elif change_type == "EXITED":
                        qoq_str = "\U0001f534 EXIT"
                    elif change_type in ("INCREASED", "DECREASED"):
                        qoq_str = _fmt_pct(change_pct) if change_pct is not None else "--"
                    else:
                        # Try the inline QoQ from the filing itself
                        inline_qoq = h.get("change_pct_qoq")
                        if inline_qoq is not None:
                            qoq_str = _fmt_pct(inline_qoq)
                        else:
                            qoq_str = "--"

                    holdings_rows.append(
                        {
                            "Ticker": ticker,
                            "Name": name,
                            "Shares": _fmt_number(shares),
                            "Value ($M)": _fmt_dollars(value, millions=True),
                            "% of Portfolio": f"{pct_port:.2f}%",
                            "QoQ Change": qoq_str,
                        }
                    )

                st.dataframe(
                    pd.DataFrame(holdings_rows),
                    hide_index=True,
                    use_container_width=True,
                )

                # Show QoQ changes detail in expander
                if changes_data and (
                    changes_data.get("new_positions")
                    or changes_data.get("increased")
                    or changes_data.get("decreased")
                    or changes_data.get("exited")
                ):
                    with st.expander("QoQ Position Changes Detail", expanded=False):
                        col_new, col_exit = st.columns(2)

                        with col_new:
                            new_pos = changes_data.get("new_positions", [])
                            if new_pos:
                                st.markdown(f"**New Positions** ({len(new_pos)})")
                                new_rows = []
                                for p in new_pos[:15]:
                                    new_rows.append(
                                        {
                                            "Ticker": p["ticker"],
                                            "Shares": _fmt_number(p["shares"]),
                                            "Value": _fmt_dollars(p["value"], millions=True),
                                        }
                                    )
                                st.dataframe(
                                    pd.DataFrame(new_rows),
                                    hide_index=True,
                                    use_container_width=True,
                                )
                            else:
                                st.caption("No new positions this quarter.")

                        with col_exit:
                            exited = changes_data.get("exited", [])
                            if exited:
                                st.markdown(f"**Exited Positions** ({len(exited)})")
                                exit_rows = []
                                for p in exited[:15]:
                                    exit_rows.append(
                                        {
                                            "Ticker": p["ticker"],
                                            "Prev Shares": _fmt_number(p.get("prev_shares", 0)),
                                            "Prev Value": _fmt_dollars(
                                                p.get("prev_value", 0), millions=True
                                            ),
                                        }
                                    )
                                st.dataframe(
                                    pd.DataFrame(exit_rows),
                                    hide_index=True,
                                    use_container_width=True,
                                )
                            else:
                                st.caption("No exited positions this quarter.")

    except ImportError as exc:
        st.error(f"Module not available: {exc}")
        st.caption("Ensure institutional_tracker.py is present in the project root.")
    except Exception as exc:
        st.error(f"Failed to load institution data: {exc}")
        st.caption(
            "SEC EDGAR may be temporarily unavailable. Data is cached for 24 hours after first fetch."
        )


# ══════════════════════════════════════════════════════════════
#  TAB 3: Options Flow
# ══════════════════════════════════════════════════════════════

with tab_options:
    render_section(
        "Options Flow Intelligence",
        subtitle="Put/call ratios, unusual volume, and large premium trades for portfolio holdings",
    )

    st.caption(
        "⚠️ Volume & Open Interest come from yfinance end-of-previous-session snapshots. "
        "Intraday real-time flow requires a paid feed (Polygon, Tradier, CBOE)."
    )

    try:
        from options_flow import get_options_flow_summary

        with st.spinner("Scanning options flow for portfolio holdings..."):
            flow_summary = get_options_flow_summary(portfolio_tickers)

        if not flow_summary:
            st.info(
                "Options flow data is unavailable. "
                "This may be due to market hours or data source limitations."
            )
        else:
            # ── Sentiment Gauge (render_kpi_row) ─────────────────────
            score = flow_summary.get("sentiment_score", 0)
            label = flow_summary.get("sentiment_label", "NEUTRAL")
            overall_pc = flow_summary.get("overall_pc_ratio")
            call_vol = flow_summary.get("call_volume_total", 0)
            put_vol = flow_summary.get("put_volume_total", 0)

            if score >= 15:
                score_dc = "positive"
            elif score <= -15:
                score_dc = "negative"
            else:
                score_dc = "neutral"

            render_kpi_row(
                [
                    {
                        "label": "Options Sentiment",
                        "value": f"{score:+d}",
                        "delta": label.replace("_", " "),
                        "delta_color": score_dc,
                    },
                    {
                        "label": "Total Call Volume",
                        "value": _fmt_number(call_vol),
                        "delta_color": "positive",
                    },
                    {
                        "label": "Total Put Volume",
                        "value": _fmt_number(put_vol),
                        "delta_color": "negative",
                    },
                    {
                        "label": "P/C Ratio (Vol)",
                        "value": _fmt_number(overall_pc, decimals=3) if overall_pc else "--",
                    },
                ]
            )

            # ── Per-Holding Put/Call Ratio Table -> st.dataframe ─────
            st.markdown("")
            render_section("Put/Call Ratio by Holding")

            ticker_signals = flow_summary.get("ticker_signals", [])
            if ticker_signals:
                pc_rows = []
                for ts in sorted(ticker_signals, key=lambda x: x.get("volume_pc_ratio") or 999):
                    tk = ts.get("ticker", "")
                    sig = ts.get("signal", "NO_DATA")
                    vpc = ts.get("volume_pc_ratio")
                    vpc_str = f"{vpc:.3f}" if vpc is not None else "--"

                    pc_rows.append(
                        {
                            "Ticker": tk,
                            "Vol P/C Ratio": vpc_str,
                            "Signal": f"{_signal_emoji(sig)} {_badge_text(sig)}",
                        }
                    )

                st.dataframe(
                    pd.DataFrame(pc_rows),
                    hide_index=True,
                    use_container_width=True,
                )

                st.caption(
                    "P/C > 1.2 = BEARISH (more puts) | P/C < 0.7 = BULLISH (more calls) | Otherwise NEUTRAL"
                )
            else:
                st.info("No per-ticker put/call data available.")

            # ── Unusual Volume Alerts -> st.dataframe ─────────────────
            st.markdown("")
            render_section("Unusual Volume Alerts")

            unusual = flow_summary.get("top_unusual_volume", [])
            if unusual:
                uv_rows = []
                for u in unusual:
                    sent = u.get("sentiment", "NEUTRAL")
                    uv_rows.append(
                        {
                            "Ticker": u.get("ticker", ""),
                            "Expiry": u.get("expiry", ""),
                            "Strike": f"${u.get('strike', 0):.1f}",
                            "Type": (u.get("type", "") or "").upper(),
                            "Volume": _fmt_number(u.get("volume", 0)),
                            "OI": _fmt_number(u.get("oi", 0)),
                            "Vol/OI": f"{u.get('vol_oi_ratio', 0):.1f}x",
                            "Est Premium": _fmt_dollars(u.get("premium_est", 0)),
                            "Moneyness": u.get("moneyness", ""),
                            "Signal": f"{_signal_emoji(sent)} {_badge_text(sent)}",
                        }
                    )

                st.dataframe(
                    pd.DataFrame(uv_rows),
                    hide_index=True,
                    use_container_width=True,
                )

                st.caption(
                    "Showing top 5 by volume/OI ratio. Vol/OI > 2.0 or volume > 5x OI flagged as unusual."
                )
            else:
                st.info("No unusual volume detected across portfolio holdings.")

            # ── Large Premium Trades -> st.dataframe ──────────────────
            st.markdown("")
            render_section("Large Premium Trades")

            large_prem = flow_summary.get("top_large_premium", [])
            if large_prem:
                lp_rows = []
                for lp in large_prem:
                    sent = lp.get("sentiment", "NEUTRAL")
                    lp_rows.append(
                        {
                            "Ticker": lp.get("ticker", ""),
                            "Expiry": lp.get("expiry", ""),
                            "Strike": f"${lp.get('strike', 0):.1f}",
                            "Type": (lp.get("type", "") or "").upper(),
                            "Volume": _fmt_number(lp.get("volume", 0)),
                            "Est Premium": _fmt_dollars(lp.get("premium_est", 0)),
                            "Moneyness": lp.get("moneyness", ""),
                            "Signal": f"{_signal_emoji(sent)} {_badge_text(sent)}",
                        }
                    )

                st.dataframe(
                    pd.DataFrame(lp_rows),
                    hide_index=True,
                    use_container_width=True,
                )

                st.caption("Showing top 5 by estimated premium. Threshold: >$50,000 notional.")
            else:
                st.info("No large premium trades detected across portfolio holdings.")

            # Timestamp footer
            scan_ts = flow_summary.get("scan_timestamp", "")
            if scan_ts:
                st.markdown("")
                st.caption(f"Options flow scanned at: {scan_ts}  |  Data cached for 30 minutes")

    except ImportError as exc:
        st.error(f"Module not available: {exc}")
        st.caption("Ensure options_flow.py is present in the project root.")
    except Exception as exc:
        st.error(f"Failed to load options flow data: {exc}")
        st.caption(
            "Options data requires market hours for live volume. "
            "Cached results are served if available (30-minute TTL)."
        )

# Floating AI Assistant
try:
    from ui.floating_chat import render_floating_ai_chat

    render_floating_ai_chat()
except Exception:
    pass
