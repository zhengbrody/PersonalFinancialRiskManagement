"""
pages/8_Institutions.py
Institutional Flow & Smart Money -- Wall Street Research Terminal
------------------------------------------------------------------
Bloomberg-inspired dark terminal for tracking institutional
positioning and 13F conviction.

REFACTORED: All raw HTML tables/grids replaced with Streamlit-native components
(st.dataframe, st.columns, st.metric, render_kpi_row) for reliable rendering.
"""

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app import cached_digest
from i18n import get_translator
from market_intelligence import fetch_macro_releases
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


def _get_portfolio_tickers() -> list:
    """Return the user's portfolio tickers, or [] if no analysis yet.

    Previously fell back to a hardcoded FAANG list which displayed as if
    it were the user's holdings — confusing and a data-attribution bug.
    Callers must handle the empty case by showing an empty-state CTA.
    """
    weights = st.session_state.get("weights")
    if weights:
        return sorted(weights.keys())
    # Sidebar's manual JSON editor input is a secondary fallback.
    import json

    try:
        raw = st.session_state.get("weights_input") or st.session_state.get("weights_json", "{}")
        parsed = json.loads(raw)
        if parsed:
            return sorted(parsed.keys())
    except Exception:
        pass
    return []


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


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def _fetch_fred_series(series_id: str) -> pd.DataFrame:
    """Fetch a public FRED series via the official CSV endpoint."""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    df = pd.read_csv(url)
    if "observation_date" not in df.columns or series_id not in df.columns:
        return pd.DataFrame(columns=["date", "value"])
    out = df.rename(columns={"observation_date": "date", series_id: "value"})[
        ["date", "value"]
    ].copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    return out.dropna(subset=["date", "value"]).sort_values("date")


def _series_snapshot(series_id: str, label: str, cadence: str, unit: str) -> dict:
    df = _fetch_fred_series(series_id)
    if df.empty:
        return {
            "Indicator": label,
            "Cadence": cadence,
            "Latest Date": "--",
            "Latest": "--",
            "Last Change": "--",
            "YoY": "--",
            "Source": "FRED",
        }

    latest = df.iloc[-1]
    previous = df.iloc[-2] if len(df) >= 2 else None
    year_ago = df.iloc[-13] if cadence == "Monthly" and len(df) >= 13 else None
    value = float(latest["value"])
    last_change = value - float(previous["value"]) if previous is not None else None
    yoy = ((value / float(year_ago["value"])) - 1.0) * 100 if year_ago is not None else None

    if unit == "pct":
        latest_text = f"{value:.2f}%"
        change_text = f"{last_change:+.2f} pp" if last_change is not None else "--"
    elif unit == "index":
        latest_text = f"{value:.1f}"
        change_text = f"{last_change:+.1f}" if last_change is not None else "--"
    elif unit == "thousands":
        latest_text = f"{value:,.0f}K"
        change_text = f"{last_change:+,.0f}K" if last_change is not None else "--"
    else:
        latest_text = f"{value:.2f}"
        change_text = f"{last_change:+.2f}" if last_change is not None else "--"

    return {
        "Indicator": label,
        "Cadence": cadence,
        "Latest Date": latest["date"].strftime("%Y-%m-%d"),
        "Latest": latest_text,
        "Last Change": change_text,
        "YoY": f"{yoy:+.2f}%" if yoy is not None else "--",
        "Source": "FRED",
    }


def _macro_release_rows() -> list[dict]:
    """Thin wrapper around the shared :func:`fetch_macro_releases` helper.

    Strips the internal/AI-only keys so the dataframe shows the original
    column set (Indicator / Cadence / Latest Date / Latest / Last Change /
    YoY / Source). The shared helper is the single source of truth used
    by both this page and the AI briefing / floating chat.
    """
    raw = fetch_macro_releases()
    if not raw:
        return [
            {
                "Indicator": "FRED unavailable",
                "Cadence": "--",
                "Latest Date": "--",
                "Latest": "--",
                "Last Change": "--",
                "YoY": "--",
                "Source": "FRED",
            }
        ]
    cols = ("Indicator", "Cadence", "Latest Date", "Latest", "Last Change", "YoY", "Source")
    return [{c: row.get(c, "--") for c in cols} for row in raw]


def _latest_numeric(series_id: str) -> float | None:
    try:
        df = _fetch_fred_series(series_id)
        if df.empty:
            return None
        return float(df.iloc[-1]["value"])
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════
#  Terminal Header
# ══════════════════════════════════════════════════════════════

now_str = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
st.markdown(
    f"""
<div class="terminal-header">
    <div class="title">MACRO & INSTITUTIONAL MONITOR</div>
    <div class="subtitle">FRED Economic Releases  |  Fed Rate Signals  |  SEC 13F Positioning</div>
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
        with st.spinner("..."):
            digest = cached_digest(
                "institutions_smart_money",
                prompt=prompt,
                max_tokens=250,
                temperature=0.2,
                invalidate_on=(
                    len(smd),
                    len(high_conviction),
                    tuple(s["ticker"] for s in high_conviction[:5]),
                ),
            )
        render_ai_digest(digest, sources="SEC 13F Filings")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════
#  Tabs
# ══════════════════════════════════════════════════════════════

tab_macro, tab_smart, tab_deepdive = st.tabs(
    [
        "Macro Release Monitor",
        "Smart Money Dashboard",
        "Institution Deep Dive",
    ]
)

portfolio_tickers = _get_portfolio_tickers()


# ══════════════════════════════════════════════════════════════
#  TAB 0: Macro Release Monitor
# ══════════════════════════════════════════════════════════════

with tab_macro:
    render_section(
        "Macro Release Monitor",
        subtitle=(
            "Daily and monthly US economic indicators used for portfolio risk context. "
            "Source: Federal Reserve Economic Data (FRED)."
        ),
    )

    rows = _macro_release_rows()
    macro_df = pd.DataFrame(rows)

    fed_lower = _latest_numeric("DFEDTARL")
    fed_upper = _latest_numeric("DFEDTARU")
    fed_funds = _latest_numeric("FEDFUNDS")
    ten_year = _latest_numeric("DGS10")
    curve = _latest_numeric("T10Y2Y")

    fed_range = (
        f"{fed_lower:.2f}% - {fed_upper:.2f}%"
        if fed_lower is not None and fed_upper is not None
        else "--"
    )
    render_kpi_row(
        [
            {"label": "Fed Target Range", "value": fed_range},
            {
                "label": "Effective Fed Funds",
                "value": f"{fed_funds:.2f}%" if fed_funds is not None else "--",
            },
            {
                "label": "10Y Treasury",
                "value": f"{ten_year:.2f}%" if ten_year is not None else "--",
            },
            {
                "label": "10Y-2Y Spread",
                "value": f"{curve:+.2f}%" if curve is not None else "--",
                "delta_color": "negative" if curve is not None and curve < 0 else "neutral",
            },
        ]
    )

    st.dataframe(macro_df, hide_index=True, use_container_width=True)
    st.caption(
        "Cadence reflects publication frequency. Latest Date is the latest observation "
        "available from FRED, not a forecast. CPI/PCE/Michigan/Unemployment/Payrolls "
        "are monthly; Fed target range and Treasury rates update daily when available."
    )

    chart_specs = [
        ("CPIAUCSL", "CPI"),
        ("PCEPI", "PCE"),
        ("UMCSENT", "Michigan Sentiment"),
        ("FEDFUNDS", "Effective Fed Funds"),
    ]
    fig_macro = go.Figure()
    for series_id, label in chart_specs:
        try:
            df = _fetch_fred_series(series_id).tail(60)
            if not df.empty:
                fig_macro.add_trace(
                    go.Scatter(
                        x=df["date"],
                        y=df["value"],
                        mode="lines",
                        name=label,
                    )
                )
        except Exception:
            continue
    fig_macro.update_layout(
        title="Selected Macro Indicators",
        height=420,
        xaxis_title="Date",
        yaxis_title="Index / Rate",
        legend_orientation="h",
    )
    st.plotly_chart(fig_macro, use_container_width=True)

    with st.expander("How this feeds portfolio risk", expanded=False):
        st.markdown("""
- CPI and PCE drive inflation expectations and discount-rate pressure on long-duration equities.
- University of Michigan sentiment helps flag consumer demand weakness before it appears in earnings.
- Fed target range and effective fed funds summarize the current policy stance.
- 10Y yield and 10Y-2Y spread show rate pressure and recession-risk pricing.
""")


# ══════════════════════════════════════════════════════════════
#  TAB 1: Smart Money Dashboard
# ══════════════════════════════════════════════════════════════

with tab_smart:
    render_section(
        "Smart Money Signals",
        subtitle="Institutional conviction analysis for your portfolio holdings (SEC 13F)",
    )

    if not portfolio_tickers:
        st.info(
            "Configure a portfolio and run analysis from the sidebar to see "
            "institutional positioning for your specific holdings."
        )
    else:
        # 13F SEC EDGAR scan is expensive (multiple HTTP fetches per ticker).
        # Cache the last result in session_state and only re-scan on explicit
        # button click — previous behavior fired on every Streamlit rerun.
        _scan_label = (
            "Rescan 13F filings"
            if st.session_state.get("smart_money_data")
            else "Scan 13F filings (SEC EDGAR)"
        )
        _rescan = st.button(_scan_label, key="institutions_rescan", type="primary")

        try:
            cached_signals = st.session_state.get("smart_money_data")
            if cached_signals and not _rescan:
                signals = cached_signals
            else:
                with st.spinner("Scanning institutional 13F filings via SEC EDGAR..."):
                    from institutional_tracker import get_smart_money_signals

                    signals = get_smart_money_signals(portfolio_tickers)
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
                        {
                            "label": "High Conviction",
                            "value": str(high_ct),
                            "delta_color": "positive",
                        },
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

# Floating AI Assistant
try:
    from ui.floating_chat import render_floating_ai_chat

    render_floating_ai_chat()
except Exception:
    pass

# Legal disclaimer footer (educational use only)
try:
    from ui.legal_footer import render_legal_footer

    render_legal_footer()
except Exception:
    pass
