"""Portfolio Copilot beta page.

This page is a lightweight PortfolioPilot-inspired workbench:
exact local quant scoring, deterministic draft-trade tooling, and optional
LLM formatting through the existing MindMarket AI provider settings.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

# Canonical public layers per the ADR-driven architecture:
#   domain/  → type-safe Pydantic input + frozen-dataclass re-exports
#   engine/  → pure NumPy/Pandas math (no LLM, no network)
#   agents/  → lightweight ReAct dispatcher with Pydantic-typed output
from agents import route_message
from domain import AssetPosition, PortfolioScore
from engine import (
    RISK_TARGETS,
    create_draft_positions,
    demo_asset_positions,
    positions_to_frame,
    score_portfolio,
)
from libs.auth.guards import require_auth_page
from ui.shared_sidebar import render_shared_sidebar
from ui.tokens import T


def _user_positions_from_session() -> list[AssetPosition] | None:
    """Build the user's real portfolio as ``AssetPosition`` records.

    Reads holdings from the active-portfolio resolver and live prices from
    ``st.session_state["prices"]`` (populated by the main Run Analysis flow).
    Never reads ``portfolio_config.PORTFOLIO_HOLDINGS`` directly here:
    authenticated users must see their own portfolio, not the owner's default.
    """
    if not st.session_state.get("analysis_ready"):
        return None
    prices = st.session_state.get("prices")
    if prices is None or getattr(prices, "empty", True):
        return None

    try:
        from libs.auth.active_portfolio import get_active_holdings

        active_holdings = get_active_holdings() or {}
    except Exception:
        active_holdings = {}
    if not active_holdings:
        return None

    positions: list[AssetPosition] = []
    for ticker, h in active_holdings.items():
        if not isinstance(h, dict):
            continue
        shares = float(h.get("shares", 0) or 0)
        if shares <= 0:
            continue
        if ticker not in prices.columns:
            continue
        series = prices[ticker].dropna()
        if series.empty:
            continue
        last_price = float(series.iloc[-1])
        if not np.isfinite(last_price) or last_price <= 0:
            continue
        market_value = shares * last_price
        avg_cost = h.get("avg_cost")
        cost_basis = float(shares) * float(avg_cost) if avg_cost not in (None, 0, 0.0) else 0.0
        asset_type_raw = str(h.get("asset_type") or _infer_asset_type(ticker))
        ap_type = "crypto" if asset_type_raw == "crypto" else "public_security"
        positions.append(
            AssetPosition(
                ticker=ticker,
                name=ticker,
                asset_type=ap_type,
                market_value=market_value,
                cost_basis=cost_basis,
                source="brokerage",
            )
        )
    return positions or None


def _infer_asset_type(ticker: str) -> str:
    tk = ticker.upper()
    if tk.endswith("-USD"):
        return "crypto"
    if tk in ("SPY", "QQQ", "IWM", "VTI", "GLD", "TLT", "VTV"):
        return "etf"
    return "equity"


def _maybe_fragment(func):
    fragment = getattr(st, "fragment", None)
    if callable(fragment):
        return fragment(func)
    return func


def _inject_css() -> None:
    st.markdown(
        f"""
        <style>
        .copilot-score {{
            border: 1px solid {T.border_subtle};
            border-radius: 8px;
            padding: 20px 22px;
            background: {T.surface};
        }}
        .copilot-score-label {{
            color: {T.text_secondary};
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }}
        .copilot-score-value {{
            color: {T.text};
            font-size: 56px;
            line-height: 1;
            font-weight: 800;
            letter-spacing: 0;
            margin-top: 8px;
        }}
        .copilot-card {{
            border: 1px solid {T.border_subtle};
            border-radius: 8px;
            padding: 16px;
            background: {T.surface};
            min-height: 142px;
        }}
        .copilot-card-title {{
            color: {T.text_secondary};
            font-size: 12px;
            font-weight: 600;
        }}
        .copilot-card-score {{
            color: {T.text};
            font-size: 28px;
            font-weight: 700;
            margin: 6px 0 4px;
        }}
        .copilot-status {{
            display: inline-block;
            border-radius: 6px;
            padding: 2px 7px;
            font-size: 11px;
            font-weight: 600;
        }}
        .copilot-detail {{
            color: {T.text_secondary};
            font-size: 12px;
            margin-top: 10px;
            line-height: 1.45;
        }}
        @media (max-width: 768px) {{
            .copilot-score-value {{ font-size: 40px; }}
            .copilot-card {{ min-height: 120px; }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _status_style(status: str) -> str:
    if status == "Excellent":
        return f"color:{T.positive};background:{T.positive_bg};"
    if status == "Good":
        return f"color:{T.text};background:{T.neutral_bg};"
    if status == "Needs Work":
        return f"color:{T.warning};background:{T.warning_bg};"
    return f"color:{T.negative};background:{T.negative_bg};"


def _format_money(value: float) -> str:
    return f"${value:,.0f}"


def _format_pct(value: float) -> str:
    return f"{value:.1%}"


def _synthetic_returns(tickers: tuple[str, ...], periods: int = 504) -> pd.DataFrame:
    """Deterministic fallback for local demos when market data is unavailable."""

    rng = np.random.default_rng(42)
    params = {
        "SPY": (0.00034, 0.0105),
        "QQQ": (0.00042, 0.0145),
        "VXUS": (0.00020, 0.0115),
        "BND": (0.00012, 0.0038),
        "BTC-USD": (0.00070, 0.0380),
    }
    index = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=periods)
    data = {}
    spy_noise = rng.normal(0.0, 1.0, periods)
    for ticker in tickers:
        mu, sigma = params.get(ticker, (0.00025, 0.0120))
        idiosyncratic = rng.normal(0.0, 1.0, periods)
        data[ticker] = mu + sigma * (0.55 * spy_noise + 0.45 * idiosyncratic)
    return pd.DataFrame(data, index=index)


def _extract_close(raw: pd.DataFrame, tickers: tuple[str, ...]) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        level_0 = set(str(x) for x in raw.columns.get_level_values(0))
        level_1 = set(str(x) for x in raw.columns.get_level_values(1))
        if "Close" in level_0:
            close = raw["Close"]
        elif "Close" in level_1:
            close = raw.xs("Close", axis=1, level=1)
        else:
            close = raw
    else:
        close = raw[["Close"]].rename(columns={"Close": tickers[0]}) if "Close" in raw else raw
    close.columns = [str(c).upper() for c in close.columns]
    return close.sort_index()


@st.cache_data(ttl=3600, show_spinner=False, max_entries=12)
def _load_market_returns(tickers: tuple[str, ...], period: str = "2y") -> tuple[pd.DataFrame, str]:
    """Load daily returns for the copilot scoring engine, with explicit fallback.

    Failure modes — each gets its own honest source label so the UI's
    "Data: …" caption tells the user when synthetic data is in play:

      * yfinance returned nothing usable → synthetic fallback
      * yfinance returned data but < 120 obs → synthetic fallback
      * yfinance returned data missing some tickers → real for hits,
        synthetic for misses, source label calls it out
    """
    import logging

    log = logging.getLogger("copilot.market_loader")

    public_tickers = tuple(sorted({t.upper() for t in tickers if t.upper() != "CASH"} | {"SPY"}))
    source = "Yahoo Finance"
    returns = pd.DataFrame()

    try:
        raw = yf.download(
            list(public_tickers),
            period=period,
            auto_adjust=True,
            progress=False,
            threads=True,
        )
        close = _extract_close(raw, public_tickers)
        returns = close.pct_change(fill_method=None).dropna(how="all")
    except Exception as exc:
        # Log the specific failure so a real outage shows in CloudWatch
        # instead of being silently masked by the synthetic fallback.
        log.warning("copilot.market_loader.yfinance_failed", exc_info=exc)

    missing = [ticker for ticker in public_tickers if ticker not in returns.columns]
    if returns.empty or len(returns) < 120:
        returns = _synthetic_returns(public_tickers)
        source = "deterministic demo fallback (live data unavailable)"
        log.info(
            "copilot.market_loader.synthetic_full",
            tickers=list(public_tickers),
            reason="empty_or_short_history",
        )
    elif missing:
        fallback = _synthetic_returns(tuple(missing), periods=len(returns))
        fallback.index = returns.index
        returns = pd.concat([returns, fallback], axis=1)
        source = f"{source} + deterministic fallback for: {', '.join(missing)}"
        log.info("copilot.market_loader.synthetic_partial", missing=missing)

    returns.columns = [str(c).upper() for c in returns.columns]
    return returns.dropna(how="all"), source


def _public_tickers(positions: list[AssetPosition]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                p.ticker.upper()
                for p in positions
                if p.enabled and p.market_value > 0 and p.asset_type != "cash"
            }
        )
    )


def _risk_pref_label(value: int) -> str:
    target = RISK_TARGETS[value]
    return f"{value} | {target['label']} " f"({float(target['annual_volatility']):.0%} vol target)"


def _score_delta(current: PortfolioScore, draft: PortfolioScore) -> str:
    delta = draft.overall_score - current.overall_score
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta} pts"


def _render_score_header(score: PortfolioScore, title: str, source_label: str) -> None:
    metric = score.metrics
    st.markdown(
        f"""
        <div class="copilot-score">
            <div class="copilot-score-label">{title}</div>
            <div class="copilot-score-value">{score.overall_score}</div>
            <div style="color:{T.text_secondary};font-size:13px;margin-top:8px;">
                {_format_money(metric.total_value)} assets · Sharpe {metric.sharpe_ratio:.2f} ·
                Vol {_format_pct(metric.annual_volatility)} · Max DD {_format_pct(metric.max_drawdown)}
            </div>
            <div style="color:{T.text_muted};font-size:11px;margin-top:6px;">
                Data: {source_label} · {metric.observations} daily observations ·
                coverage {_format_pct(metric.data_coverage)}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_dimension_cards(score: PortfolioScore) -> None:
    cols = st.columns(3)
    for col, dim in zip(cols, score.dimensions.values()):
        with col:
            st.markdown(
                f"""
                <div class="copilot-card">
                    <div class="copilot-card-title">{dim.name}</div>
                    <div class="copilot-card-score">{dim.score:.1f}<span style="font-size:13px;color:{T.text_secondary};"> / 10</span></div>
                    <span class="copilot-status" style="{_status_style(dim.status)}">{dim.status}</span>
                    <div class="copilot-detail">{dim.detail}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def _render_metric_strip(score: PortfolioScore) -> None:
    metric = score.metrics
    cols = st.columns(5)
    values = [
        ("Annual Return", _format_pct(metric.annual_return)),
        ("Volatility", _format_pct(metric.annual_volatility)),
        ("Sharpe", f"{metric.sharpe_ratio:.2f}"),
        (
            "Beta",
            (
                "N/A"
                if not np.isfinite(metric.beta_to_benchmark)
                else f"{metric.beta_to_benchmark:.2f}"
            ),
        ),
        ("Daily VaR 95%", _format_pct(metric.var_95_daily)),
    ]
    for col, (label, value) in zip(cols, values):
        col.metric(label, value)


def _score_bar(score: PortfolioScore, title: str) -> go.Figure:
    names = [dim.name for dim in score.dimensions.values()]
    values = [dim.score for dim in score.dimensions.values()]
    colors = [T.positive if v >= 8 else T.warning if v >= 4 else T.negative for v in values]
    fig = go.Figure(
        go.Bar(
            x=names,
            y=values,
            marker_color=colors,
            text=[f"{v:.1f}" for v in values],
            textposition="outside",
        )
    )
    fig.update_layout(
        title=title,
        height=300,
        yaxis=dict(range=[0, 10], title="Score"),
        xaxis=dict(title=None),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=48, b=20),
        showlegend=False,
    )
    return fig


def _weights_bar(current: list[AssetPosition], draft: list[AssetPosition]) -> go.Figure:
    current_frame = positions_to_frame(current)
    draft_frame = positions_to_frame(draft)
    active = current_frame[current_frame["Enabled"] & (current_frame["Market Value"] > 0)]
    tickers = active["Ticker"].tolist()
    cur_weights = [
        float(current_frame.loc[current_frame["Ticker"] == ticker, "Weight"].iloc[0]) * 100
        for ticker in tickers
    ]
    draft_weights = [
        float(draft_frame.loc[draft_frame["Ticker"] == ticker, "Weight"].iloc[0]) * 100
        for ticker in tickers
    ]
    fig = go.Figure()
    fig.add_trace(go.Bar(name="Current", x=tickers, y=cur_weights, marker_color=T.neutral))
    fig.add_trace(go.Bar(name="Draft", x=tickers, y=draft_weights, marker_color=T.accent))
    fig.update_layout(
        barmode="group",
        height=320,
        yaxis=dict(title="Weight (%)"),
        xaxis=dict(title=None),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=30, b=20),
        legend=dict(orientation="h", y=1.08),
    )
    return fig


def _llm_callable(prompt: str, system: str, max_tokens: int, temperature: float) -> str:
    from ui.floating_chat import _chat_call_llm

    return _chat_call_llm(
        prompt=prompt,
        system=system,
        max_tokens=max_tokens,
        temperature=temperature,
        stream=False,
    )


@_maybe_fragment
def _render_scoring_panel(score: PortfolioScore, source_label: str) -> None:
    _render_score_header(score, "Portfolio Score", source_label)
    st.write("")
    _render_dimension_cards(score)
    st.write("")
    _render_metric_strip(score)


render_shared_sidebar()
require_auth_page(
    "AI Portfolio Copilot Beta",
    description=(
        "A portfolio workbench that combines deterministic quant scoring, "
        "draft portfolio changes, and lightweight AI assistance for your own "
        "holdings."
    ),
    features=[
        "Score your portfolio across concentration, diversification, and risk dimensions.",
        "Draft sandbox allocations before committing changes.",
        "Ask a portfolio-aware assistant about tradeoffs and next actions.",
    ],
)
_inject_css()

st.markdown("## AI Portfolio Copilot Beta")
st.caption(
    "Exact quant scoring, draft portfolio sandbox, and lightweight "
    "resident agents — running on your real portfolio."
)

_user_positions = _user_positions_from_session()
if _user_positions is None:
    # No prior Run Analysis → fall back to demo so first-time visitors
    # can still see what the page does. Banner makes the data origin
    # explicit so they don't think the demo is their own portfolio.
    st.info(
        "📊 No analysis yet. Showing a **demo portfolio** so you can "
        "preview the Copilot. Run **Run Analysis** on the Dashboard "
        "to switch this page to your real holdings.",
        icon="ℹ️",
    )
    base_positions = demo_asset_positions(100_000.0)
    _portfolio_source_label = "Demo portfolio"
else:
    base_positions = _user_positions
    _portfolio_source_label = f"Your portfolio ({len(base_positions)} positions)"
    st.caption(f"📁 Data source: {_portfolio_source_label}")
public_tickers = _public_tickers(base_positions)
market_returns, market_source = _load_market_returns(public_tickers, period="2y")
benchmark_returns = market_returns["SPY"] if "SPY" in market_returns.columns else None

control_col, note_col = st.columns([1, 2])
with control_col:
    risk_preference = st.select_slider(
        "Risk preference",
        options=[1, 2, 3, 4, 5],
        value=3,
        format_func=_risk_pref_label,
        key="copilot_risk_preference",
    )
with note_col:
    risk_free_rate = st.number_input(
        "Risk-free rate",
        min_value=0.0,
        max_value=0.12,
        value=0.045,
        step=0.005,
        format="%.3f",
        key="copilot_risk_free_rate",
    )

current_score = score_portfolio(
    base_positions,
    market_returns,
    benchmark_returns=benchmark_returns,
    risk_preference=risk_preference,
    risk_free_rate=risk_free_rate,
)

_render_scoring_panel(current_score, market_source)
if current_score.metrics.data_quality_notes:
    with st.expander("Data quality notes", expanded=False):
        for note in current_score.metrics.data_quality_notes:
            st.write(f"- {note}")

st.plotly_chart(
    _score_bar(current_score, "Score Dimensions"),
    width="stretch",
    config={"displayModeBar": False},
)

st.markdown("---")
st.markdown("### Asset Aggregation")
positions_frame = positions_to_frame(base_positions)
display_frame = positions_frame[positions_frame["Enabled"]].copy()
st.dataframe(
    display_frame[
        [
            "Ticker",
            "Type",
            "Source",
            "Market Value",
            "Weight",
            "Cost Basis",
            "Unrealized P&L",
            "Unrealized P&L %",
            "Expense Ratio",
            "Proxy",
        ]
    ],
    hide_index=True,
    width="stretch",
    column_config={
        "Market Value": st.column_config.NumberColumn(format="$%.0f"),
        "Weight": st.column_config.NumberColumn(format="%.1%"),
        "Cost Basis": st.column_config.NumberColumn(format="$%.0f"),
        "Unrealized P&L": st.column_config.NumberColumn(format="$%.0f"),
        "Unrealized P&L %": st.column_config.NumberColumn(format="%.1%"),
        "Expense Ratio": st.column_config.NumberColumn(format="%.2%"),
    },
)

with st.expander("Reserved connectors", expanded=False):
    reserved = positions_frame[~positions_frame["Enabled"]]
    st.dataframe(
        reserved[["Ticker", "Name", "Type", "Source", "Enabled"]],
        hide_index=True,
        width="stretch",
    )

st.markdown("---")
st.markdown("### Sandbox Simulation")


@_maybe_fragment
def _render_sandbox(
    base_positions_arg: list[AssetPosition],
    market_returns_arg: pd.DataFrame,
    benchmark_returns_arg: pd.Series | None,
    current_score_arg: PortfolioScore,
    risk_preference_arg: int,
    risk_free_rate_arg: float,
) -> None:
    """Sandbox slider block, isolated behind st.fragment (ADR 03).

    With the @st.fragment decorator each slider drag re-runs ONLY this
    function — the outer page (market-data fetch, asset table render,
    score header) stays cached. Without this, every drag re-fetches
    yfinance and re-renders ~600 lines of the page.

    The draft score + positions are stashed into session_state so the
    chat fragment (also isolated) can read them without triggering its
    own re-run of the sliders.
    """
    draft_enabled_local = st.toggle(
        "Create Draft Portfolio",
        value=st.session_state.get("copilot_draft_enabled", False),
        key="copilot_draft_enabled",
    )

    if not draft_enabled_local:
        # Clear any cached draft so the chat fragment falls back to the
        # baseline portfolio when the user disables the sandbox.
        st.session_state.pop("_copilot_draft_score", None)
        st.session_state.pop("_copilot_draft_positions", None)
        return

    try:
        active_frame_local = positions_to_frame(base_positions_arg)
        active_frame_local = active_frame_local[
            active_frame_local["Enabled"] & (active_frame_local["Market Value"] > 0)
        ]
        if active_frame_local.empty:
            st.warning(
                "No active positions with positive market value to simulate — "
                "add holdings before opening the sandbox."
            )
            return

        total_value_local = float(active_frame_local["Market Value"].sum())
        st.caption(
            "Adjust target weights; values are normalized automatically "
            "and do not affect live holdings."
        )
        raw_weights: dict[str, float] = {}
        slider_cols_local = st.columns(2)
        for i, row in enumerate(active_frame_local.to_dict("records")):
            ticker_local = str(row["Ticker"])
            default_weight = float(row["Weight"]) * 100.0
            with slider_cols_local[i % 2]:
                raw_weights[ticker_local] = st.slider(
                    ticker_local,
                    min_value=0.0,
                    max_value=80.0,
                    value=float(round(default_weight, 1)),
                    step=0.5,
                    key=f"copilot_weight_{ticker_local}",
                )

        normalized_local = {tk: v / 100.0 for tk, v in raw_weights.items()}
        draft_positions_local = create_draft_positions(
            base_positions_arg, normalized_local, total_value=total_value_local
        )
        draft_score_local = score_portfolio(
            draft_positions_local,
            market_returns_arg,
            benchmark_returns=benchmark_returns_arg,
            risk_preference=risk_preference_arg,
            risk_free_rate=risk_free_rate_arg,
        )
    except ValueError as exc:
        # Bad weights, no data overlap, etc. — surface explicitly
        # rather than letting the page 500.
        st.error(f"Sandbox could not score the draft portfolio: {exc}")
        return

    # Stash for the chat fragment below.
    st.session_state["_copilot_draft_score"] = draft_score_local
    st.session_state["_copilot_draft_positions"] = draft_positions_local

    compare_cols_local = st.columns(3)
    compare_cols_local[0].metric("Current Score", current_score_arg.overall_score)
    compare_cols_local[1].metric(
        "Draft Score",
        draft_score_local.overall_score,
        _score_delta(current_score_arg, draft_score_local),
    )
    compare_cols_local[2].metric(
        "Draft Volatility",
        _format_pct(draft_score_local.metrics.annual_volatility),
        f"{draft_score_local.metrics.annual_volatility - current_score_arg.metrics.annual_volatility:+.1%}",
    )
    st.plotly_chart(
        _weights_bar(base_positions_arg, draft_positions_local),
        width="stretch",
        config={"displayModeBar": False},
    )
    with st.expander("Draft score detail", expanded=True):
        _render_dimension_cards(draft_score_local)


_render_sandbox(
    base_positions,
    market_returns,
    benchmark_returns,
    current_score,
    risk_preference,
    risk_free_rate,
)

# The chat fragment reads any active draft directly from session_state
# inside _render_chat() so sandbox re-runs don't propagate into the
# chat (and vice versa). No module-level pass-through needed.

st.markdown("---")
st.markdown("### AI Assistant")
st.caption(
    "The router dispatches to Portfolio Analyzer or Strategy Optimizer based on your message."
)


@_maybe_fragment
def _render_chat(
    base_positions_arg: list[AssetPosition],
    current_score_arg: PortfolioScore,
) -> None:
    """Chat block, isolated behind st.fragment.

    A chat_input submission only re-runs this function — no re-fetch
    of market data, no re-render of the sliders or score panel above.
    Reads the current draft (if any) from session_state.
    """
    if "copilot_chat_messages" not in st.session_state:
        st.session_state["copilot_chat_messages"] = [
            {
                "role": "assistant",
                "content": (
                    "Ask for a portfolio diagnosis, fee scan, "
                    "tax-loss harvesting review, or draft trades. "
                    "Quant metrics are read from the local scoring engine."
                ),
            }
        ]

    for message in st.session_state["copilot_chat_messages"]:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    user_prompt_local = st.chat_input("Ask the MindMarket AI copilot about this portfolio")
    if not user_prompt_local:
        return

    st.session_state["copilot_chat_messages"].append({"role": "user", "content": user_prompt_local})
    with st.chat_message("user"):
        st.markdown(user_prompt_local)

    # Resolve sandbox-vs-baseline target each turn — the sandbox
    # fragment may have updated its session_state between turns.
    draft_score_now = st.session_state.get("_copilot_draft_score")
    draft_positions_now = st.session_state.get("_copilot_draft_positions")
    target_score = draft_score_now or current_score_arg
    target_positions = draft_positions_now or base_positions_arg

    with st.chat_message("assistant"):
        with st.spinner("Routing to portfolio agents..."):
            llm = _llm_callable if st.session_state.get("_llm_configured") else None
            # `route_message` returns a Pydantic `AgentResponse` and
            # catches router exceptions internally so a bad LLM key /
            # transient failure surfaces as text, not a 500.
            response = route_message(
                user_prompt_local,
                target_score,
                target_positions,
                llm_callable=llm,
            )
        st.markdown(response.response_markdown)
        if response.draft_trades:
            st.dataframe(
                pd.DataFrame(response.draft_trades),
                hide_index=True,
                width="stretch",
            )
        with st.expander("Agent trace", expanded=False):
            st.write(f"Route: {response.agent_name}")
            for step in response.tool_trace:
                st.write(f"- {step}")
            if response.grounded_in:
                st.caption("Grounded in (exact engine outputs the agent was " "allowed to cite):")
                st.json(response.grounded_in, expanded=False)

    st.session_state["copilot_chat_messages"].append(
        {
            "role": "assistant",
            "content": response.response_markdown,
        }
    )


_render_chat(base_positions, current_score)
