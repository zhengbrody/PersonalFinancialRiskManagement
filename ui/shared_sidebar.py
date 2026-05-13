"""
ui/shared_sidebar.py
Shared Sidebar Component - Displays consistently across all pages
"""

import json

import streamlit as st

from i18n import get_translator


def _safe_get_secret(key):
    """Safely get secret from Streamlit secrets"""
    try:
        return st.secrets.get(key, "")
    except Exception:
        return ""


def _truthy(value) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


_NAV_GROUPS = [
    (
        "Start Here",
        [
            ("app.py", "Dashboard"),
            ("pages/0_Login.py", "Login"),
            ("pages/0_Portfolios.py", "Portfolios"),
            ("pages/6_Guided_Analysis.py", "Guided Analysis"),
        ],
    ),
    (
        "Portfolio Risk",
        [
            ("pages/1_Overview.py", "Overview"),
            ("pages/2_Risk.py", "Risk"),
            ("pages/4_Portfolio.py", "Portfolio Actions"),
        ],
    ),
    (
        "Market Context",
        [
            ("pages/3_Markets.py", "Markets"),
            ("pages/5_TradingView.py", "TradingView"),
            ("pages/7_Trading_Floor.py", "Trading Floor"),
        ],
    ),
    (
        "Research",
        [
            ("pages/10_Ticker_Research.py", "Ticker Research"),
            ("pages/8_Institutions.py", "Institutions"),
            ("pages/9_Quant_Lab.py", "Quant Lab"),
        ],
    ),
    (
        "System",
        [
            ("pages/97_Owner_Admin_Status.py", "Owner Admin Status"),
            ("pages/99_Legal.py", "Legal"),
        ],
    ),
]


def _render_custom_navigation() -> None:
    """Render custom English navigation because Streamlit's native page nav is static."""
    try:
        st.markdown(
            """
            <style>
            [data-testid="stSidebarNav"] { display: none !important; }
            </style>
            """,
            unsafe_allow_html=True,
        )
    except Exception:
        pass

    try:
        from libs.admin.status import is_owner_email
        from libs.auth.session import current_user

        _user = current_user() or {}
        show_owner = is_owner_email(_user.get("email"))
    except Exception:
        show_owner = False

    st.markdown("### Navigation")
    for group_label, items in _NAV_GROUPS:
        st.markdown(
            (
                f"<div style='margin:12px 0 4px 0;color:#8B949E;font-size:11px;"
                f"font-weight:600;text-transform:uppercase;letter-spacing:0.08em;'>"
                f"{group_label}</div>"
            ),
            unsafe_allow_html=True,
        )
        for path, label in items:
            if "97_Owner_Admin_Status.py" in path and not show_owner:
                continue
            st.page_link(path, label=label)


def _queue_analysis_and_route(
    *, force_refresh: bool = False, route_after: str = "pages/1_Overview.py"
) -> None:
    """Queue an analysis run and route through the dashboard executor.

    Each Streamlit page script runs independently, so importing `app.py`
    directly from page routes can produce inconsistent behavior. The sidebar
    therefore only writes trigger flags here, then returns to `app.py` where
    the canonical analysis execution path already lives.
    """
    st.session_state["_run_trigger"] = True
    st.session_state["_route_after_analysis"] = route_after
    if force_refresh:
        st.session_state["_force_refresh"] = True
    try:
        st.switch_page("app.py")
    except Exception:
        st.rerun()


def render_shared_sidebar():
    """
    Render the shared sidebar that appears on all pages.
    This ensures consistent navigation and controls across the app.

    Returns:
        tuple: (lang, t) - language code and translator function
    """

    # Prevent duplicate rendering within the same script run.
    # Each page calls render_shared_sidebar(); importing app.py may trigger
    # it a second time.  We use the Streamlit script-run-ctx id so the flag
    # resets automatically on every rerun.
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        _ctx = get_script_run_ctx()
        if _ctx is not None:
            _run_id = _ctx.script_run_id
            if st.session_state.get("_sidebar_run_id") == _run_id:
                return "en", get_translator("en")
            st.session_state["_sidebar_run_id"] = _run_id
    except Exception:
        pass  # If we can't detect duplicate, just render

    # Product simplification: keep the app UI in English only.
    # Browser translation works better than maintaining a second visible UI layer.
    st.session_state["_lang"] = "en"
    current_lang = "en"

    with st.sidebar:
        _render_custom_navigation()
        st.markdown("---")

        # ── Logo and Title ────────────────────────────────────────
        st.markdown(
            """
        <div style="text-align: center; padding: 20px 0 10px 0;">
            <div style="font-size: 28px; font-weight: 800; color: #0B7285; letter-spacing: -0.5px;">
                MindMarket AI
            </div>
            <div style="color: #8B949E; font-size: 11px; font-weight: 500; letter-spacing: 1px; margin-top: 4px;">
                PORTFOLIO RISK ANALYTICS
            </div>
        </div>
        """,
            unsafe_allow_html=True,
        )

        st.markdown("---")

        # ── Portfolio Configuration ───────────────────────────────
        st.markdown("### 📊 " + ("Portfolio" if current_lang == "en" else "组合"))

        # Combined Refresh + Run button (replaces separate Refresh and Run Analysis)
        _run_label_live = (
            "🚀 Refresh & Run Analysis" if current_lang == "en" else "🚀 刷新并运行分析"
        )
        # Active-portfolio resolver: when user is logged in with a DB portfolio,
        # use that; otherwise fall back to the hardcoded portfolio_config defaults.
        # See libs/auth/active_portfolio.py for the decision tree.
        try:
            from libs.auth.active_portfolio import (
                get_active_holdings,
                get_active_margin_loan,
                get_active_portfolio_meta,
            )

            _active_meta = get_active_portfolio_meta()
        except Exception:
            _active_meta = {"name": "Built-in demo portfolio", "source": "hardcoded"}

        # Inline banner so user knows which portfolio is loaded
        _active_source = _active_meta.get("source")
        if _active_source == "supabase":
            st.caption(
                f"📂 Active: **{_active_meta['name']}** (your DB portfolio)"
                if current_lang == "en"
                else f"📂 当前组合：**{_active_meta['name']}**（你的数据库组合）"
            )
        elif _active_source == "empty":
            # Authed user with no portfolios — block analysis to avoid silently
            # showing the dev's hardcoded holdings (data leak).
            st.warning(
                "No portfolio yet. Create one on the Portfolios page to enable analysis."
                if current_lang == "en"
                else "尚无组合。请先在「我的组合」页面创建后再运行分析。"
            )
            st.page_link(
                "pages/0_Portfolios.py",
                label=("→ Go to Portfolios" if current_lang == "en" else "→ 前往「我的组合」"),
            )
        else:
            st.caption(
                f"📂 Active: **{_active_meta['name']}**"
                if current_lang == "en"
                else f"📂 当前组合：**{_active_meta['name']}**"
            )

        _block_run = _active_source == "empty"

        if (
            st.button(
                _run_label_live,
                type="primary",
                use_container_width=True,
                key="refresh_and_run",
                disabled=_block_run,
            )
            and not _block_run
        ):
            try:
                import importlib

                import yfinance as yf

                import portfolio_config as _pc

                importlib.reload(_pc)
                # Resolved at click-time so changes to user's DB portfolio
                # picked up without restarting Streamlit.
                try:
                    PORTFOLIO_HOLDINGS = get_active_holdings()
                    MARGIN_LOAN = get_active_margin_loan()
                except Exception:
                    PORTFOLIO_HOLDINGS = _pc.PORTFOLIO_HOLDINGS
                    MARGIN_LOAN = _pc.MARGIN_LOAN
                from logging_config import get_logger

                logger = get_logger(__name__)
                logger.info(
                    "ui.button.refresh_and_run_clicked",
                    portfolio_source=_active_meta.get("source"),
                    portfolio_name=_active_meta.get("name"),
                )

                def _shares(t):
                    h = PORTFOLIO_HOLDINGS[t]
                    return h["shares"] if isinstance(h, dict) else h

                with st.spinner(
                    "Fetching live prices..." if current_lang == "en" else "获取实时价格..."
                ):
                    tickers = list(PORTFOLIO_HOLDINGS.keys())
                    data = yf.download(tickers, period="5d", progress=False)
                    current_prices = {}
                    for tk in tickers:
                        try:
                            if isinstance(data.columns, __import__("pandas").MultiIndex):
                                if tk in data["Close"].columns:
                                    price = data["Close"][tk].dropna().iloc[-1]
                                    current_prices[tk] = float(price)
                            else:
                                price = data["Close"].dropna().iloc[-1]
                                current_prices[tk] = float(price)
                        except Exception:
                            logger.warning("ui.refresh.price_missing", ticker=tk)

                values = {t: _shares(t) * current_prices.get(t, 0) for t in tickers}
                total_value = sum(values.values())

                if total_value <= 0:
                    st.error("Failed: could not fetch any prices")
                else:
                    live_weights = {t: v / total_value for t, v in values.items() if v > 0}
                    net_equity = total_value - MARGIN_LOAN
                    # Contributed-capital from portfolio_config is the dev's
                    # principal. Only use it for the anonymous-demo source;
                    # for real users we derive from holdings' avg_cost below
                    # (Position P&L), and leave return-on-capital unset.
                    if _active_meta.get("source") == "hardcoded":
                        contributed_capital = getattr(
                            _pc,
                            "CONTRIBUTED_CAPITAL",
                            getattr(_pc, "TOTAL_COST_BASIS", 0),
                        )
                    else:
                        contributed_capital = 0
                    return_on_capital_dollar = (
                        net_equity - contributed_capital if contributed_capital > 0 else None
                    )
                    return_on_capital_pct = (
                        (net_equity - contributed_capital) / contributed_capital
                        if contributed_capital > 0
                        else None
                    )

                    # Position-level P&L from avg_cost (works for both DB and
                    # hardcoded sources because PORTFOLIO_HOLDINGS is the unified
                    # shape now).
                    position_pnl_dollar = None
                    position_pnl_pct = None
                    position_cost_info = None
                    try:
                        # Compute inline so we don't depend on portfolio_config's
                        # `position_cost_summary` helper (which only sees the
                        # hardcoded constants, not the user's DB rows).
                        total_position_cost = 0.0
                        tickers_with_cost = []
                        for tk, h in PORTFOLIO_HOLDINGS.items():
                            if isinstance(h, dict) and h.get("avg_cost") is not None:
                                cost = float(h["shares"]) * float(h["avg_cost"])
                                total_position_cost += cost
                                tickers_with_cost.append(tk)
                        if total_position_cost > 0:
                            known = set(tickers_with_cost)
                            covered_long = sum(v for tk, v in values.items() if tk in known)
                            position_pnl_dollar = covered_long - total_position_cost
                            position_pnl_pct = position_pnl_dollar / total_position_cost
                            position_cost_info = {
                                "total_position_cost": total_position_cost,
                                "tickers_with_cost": tickers_with_cost,
                                "coverage_by_value": (
                                    covered_long / total_value if total_value > 0 else 0
                                ),
                            }
                    except Exception:
                        pass

                    # Per-account breakdown.
                    # _pc.ACCOUNTS + _pc.account_summary() iterate the dev's
                    # hardcoded holdings, so we only use that path for the
                    # anonymous demo. For DB-backed users, group by each
                    # holding's "account" key.
                    account_breakdown = {}
                    try:
                        if (
                            _active_meta.get("source") == "hardcoded"
                            and hasattr(_pc, "ACCOUNTS")
                            and hasattr(_pc, "account_summary")
                        ):
                            for acct_name in _pc.ACCOUNTS:
                                account_breakdown[acct_name] = _pc.account_summary(
                                    acct_name, values
                                )
                        else:
                            for tk, h in PORTFOLIO_HOLDINGS.items():
                                if not isinstance(h, dict):
                                    continue
                                acct = h.get("account") or "default"
                                bucket = account_breakdown.setdefault(
                                    acct,
                                    {
                                        "total_long": 0.0,
                                        "tickers": [],
                                        "margin_loan": 0.0,
                                    },
                                )
                                bucket["total_long"] += float(values.get(tk, 0.0))
                                bucket["tickers"].append(tk)
                            # Attribute the user's total margin loan to the
                            # first account containing a margin-eligible
                            # holding (single-loan model — keeps schema simple).
                            if MARGIN_LOAN and account_breakdown:
                                first_acct = next(iter(account_breakdown))
                                account_breakdown[first_acct]["margin_loan"] = float(MARGIN_LOAN)
                    except Exception:
                        pass

                    meta = {
                        "total_long": total_value,
                        "net_equity": net_equity,
                        "margin_loan": MARGIN_LOAN,
                        "sector_map": _pc.build_sector_map(PORTFOLIO_HOLDINGS),
                        "leverage": total_value / net_equity if net_equity > 0 else float("inf"),
                        "missing": [t for t in tickers if t not in current_prices],
                        "contributed_capital": contributed_capital,
                        "return_on_capital_dollar": return_on_capital_dollar,
                        "return_on_capital_pct": return_on_capital_pct,
                        "position_pnl_dollar": position_pnl_dollar,
                        "position_pnl_pct": position_pnl_pct,
                        "position_cost_info": position_cost_info,
                        "account_breakdown": account_breakdown,
                        # Back-compat aliases
                        "cost_basis": contributed_capital,
                        "total_pnl": return_on_capital_dollar,
                        "total_pnl_pct": return_on_capital_pct,
                    }

                    st.session_state.weights_json = json.dumps(live_weights, indent=2)
                    st.session_state.weights_input = st.session_state.weights_json
                    st.session_state._portfolio_meta = meta
                    st.session_state.last_weights_json = None
                    logger.info(
                        "ui.refresh_and_run.success",
                        ticker_count=len(live_weights),
                        total_long=round(total_value, 2),
                        net_equity=round(net_equity, 2),
                    )
                    _queue_analysis_and_route(force_refresh=True)
            except Exception as e:
                st.error(f"Failed: {str(e)}")

        # Secondary "Run with current weights" — for when user edits JSON manually
        _run_label_current = (
            "Run with Current Weights" if current_lang == "en" else "用当前权重运行"
        )
        if st.button(_run_label_current, use_container_width=True, key="run_current_only"):
            _queue_analysis_and_route(force_refresh=False)

        # Force Refresh — bypasses cache regardless of whether any param changed.
        # Useful when prices may have moved but analysis params haven't, or when
        # user explicitly wants a fresh Monte Carlo roll.
        _force_label = "🔄 Force Refresh" if current_lang == "en" else "🔄 强制刷新"
        if st.button(
            _force_label,
            use_container_width=True,
            key="force_refresh_btn",
            help=(
                "Invalidate the analysis cache and recompute from scratch."
                if current_lang == "en"
                else "清除分析缓存并重新计算。"
            ),
        ):
            _queue_analysis_and_route(force_refresh=True)

        # Portfolio Metadata (if available)
        if meta := getattr(st.session_state, "_portfolio_meta", None):
            st.caption(f"💰 Net Equity: ${meta.get('net_equity', meta['total_long']):,.0f}")
            st.caption(f"📈 Total Long: ${meta['total_long']:,.0f}")
            st.caption(f"🏦 Margin: ${meta.get('margin_loan', 0):,.0f}")
            st.caption(f"⚖️ Leverage: {meta['leverage']:.2f}x")

            # Capital & P&L (new metric names; back-compat aliases kept)
            _cc = meta.get("contributed_capital", meta.get("cost_basis", 0))
            _roc_d = meta.get("return_on_capital_dollar", meta.get("total_pnl"))
            _roc_p = meta.get("return_on_capital_pct", meta.get("total_pnl_pct"))
            if _cc and _cc > 0 and _roc_d is not None:
                _icon = "🟢" if _roc_d >= 0 else "🔴"
                st.caption(f"💵 Contributed Capital: ${_cc:,.0f}")
                st.caption(f"{_icon} Return on Capital: ${_roc_d:+,.0f} ({_roc_p:+.1%})")
            # Optional position P&L (only if avg_cost populated)
            _pos_pnl = meta.get("position_pnl_dollar")
            _pos_pnl_pct = meta.get("position_pnl_pct")
            if _pos_pnl is not None and _pos_pnl_pct is not None:
                _icon2 = "🟢" if _pos_pnl >= 0 else "🔴"
                st.caption(f"{_icon2} Position P&L: ${_pos_pnl:+,.0f} ({_pos_pnl_pct:+.1%})")

            # Per-account breakdown (compact)
            acct_break = meta.get("account_breakdown") or {}
            if acct_break and len(acct_break) > 1:
                with st.expander("Per-account view", expanded=False):
                    for name, info in acct_break.items():
                        if info.get("total_long", 0) <= 0:
                            continue
                        lev = info.get("leverage", 1.0)
                        lev_str = f"{lev:.2f}x" if lev != float("inf") else "∞"
                        st.caption(
                            f"**{name}** ({info.get('type','?')}): "
                            f"long=${info['total_long']:,.0f} · "
                            f"loan=${info['margin_loan']:,.0f} · "
                            f"equity=${info['net_equity']:,.0f} · "
                            f"lev={lev_str}"
                        )

        # Config validation warnings — one-shot on first render this session.
        if not st.session_state.get("_portfolio_config_checked"):
            try:
                import portfolio_config as _pc

                _issues = (
                    _pc.validate_portfolio_config()
                    if hasattr(_pc, "validate_portfolio_config")
                    else []
                )
                st.session_state._portfolio_config_issues = _issues
                st.session_state._portfolio_config_checked = True
            except Exception:
                st.session_state._portfolio_config_issues = []
                st.session_state._portfolio_config_checked = True
        _cfg_issues = st.session_state.get("_portfolio_config_issues") or []
        _show_cfg_issues = _truthy(_safe_get_secret("MINDMARKET_SHOW_CONFIG_WARNINGS"))
        try:
            from libs.admin.status import is_owner_email
            from libs.auth.session import current_user

            _show_cfg_issues = _show_cfg_issues or is_owner_email(
                (current_user() or {}).get("email")
            )
        except Exception:
            pass
        if _cfg_issues and _show_cfg_issues:
            with st.expander(f"⚠️ Portfolio config: {len(_cfg_issues)} warning(s)", expanded=False):
                for _iss in _cfg_issues:
                    st.caption(f"• {_iss}")

        # Initialize weights_json if not exists
        if "weights_json" not in st.session_state:
            st.session_state.weights_json = json.dumps(
                {"AAPL": 0.4, "TSLA": 0.3, "BTC-USD": 0.3}, indent=2
            )

        # Handle example portfolio selection (from main page buttons)
        if "_example_portfolio" in st.session_state:
            st.session_state.weights_json = st.session_state._example_portfolio
            del st.session_state._example_portfolio

        # Weights Input
        st.caption("Weights (JSON)" if current_lang == "en" else "权重 (JSON)")
        weights_json = st.text_area(
            "Portfolio Weights" if current_lang == "en" else "组合权重",
            value=st.session_state.weights_json,
            height=120,
            label_visibility="collapsed",
        )

        st.markdown("---")

        # ── Analysis Parameters ───────────────────────────────────
        st.markdown("### ⚙️ " + ("Parameters" if current_lang == "en" else "参数"))

        col1, col2 = st.columns(2)
        with col1:
            period_years = st.slider(
                "History (yr)" if current_lang == "en" else "历史（年）",
                min_value=1,
                max_value=5,
                value=st.session_state.get("period_years", 2),
                key="period_years_sidebar",
            )

        with col2:
            mc_sims = st.select_slider(
                "MC Sims" if current_lang == "en" else "蒙特卡洛",
                options=[1000, 5000, 10000, 20000, 50000],
                value=st.session_state.get("mc_sims", 10000),
                key="mc_sims_sidebar",
            )

        col3, col4 = st.columns(2)
        with col3:
            mc_horizon = st.slider(
                "Horizon (d)" if current_lang == "en" else "周期（天）",
                min_value=5,
                max_value=63,
                value=st.session_state.get("mc_horizon", 21),
                key="mc_horizon_sidebar",
            )

        with col4:
            market_shock_pct = st.slider(
                "Shock (%)" if current_lang == "en" else "冲击 (%)",
                min_value=-30,
                max_value=0,
                value=int(st.session_state.get("market_shock", -0.10) * 100),
                key="market_shock_sidebar",
            )
            market_shock = market_shock_pct / 100

        # Risk-free rate
        risk_free_rate = (
            st.number_input(
                "Risk-Free Rate (%)" if current_lang == "en" else "无风险利率 (%)",
                min_value=0.0,
                max_value=15.0,
                value=4.5,
                step=0.1,
                key="risk_free_rate_sidebar",
            )
            / 100
        )

        st.markdown("---")

        # ── AI Provider Configuration ─────────────────────────────
        # ══════════════════════════════════════════════════════════
        #  Admin mode toggle
        # ──────────────────────────────────────────────────────────
        # MINDMARKET_ADMIN_MODE=true is only an owner/dev quota bypass.
        # Raw API-key inputs stay hidden unless the owner explicitly sets
        # MINDMARKET_SHOW_API_INPUTS=true for local debugging.
        # Anything else → end-user mode: keys are server-side only.
        # ══════════════════════════════════════════════════════════
        import os as _os_admin

        _admin_mode = _truthy(
            _os_admin.environ.get("MINDMARKET_ADMIN_MODE", "")
            or _safe_get_secret("MINDMARKET_ADMIN_MODE")
        )
        _show_api_inputs = _truthy(
            _os_admin.environ.get("MINDMARKET_SHOW_API_INPUTS", "")
            or _safe_get_secret("MINDMARKET_SHOW_API_INPUTS")
        )
        _api_ui_mode = _admin_mode and _show_api_inputs

        if _api_ui_mode:
            st.markdown(
                "### 🤖 AI Provider (admin)" if current_lang == "en" else "### 🤖 AI 提供方 (admin)"
            )
        else:
            st.markdown("### 🤖 AI Access" if current_lang == "en" else "### 🤖 AI 访问")

        # ── Detect if running in cloud/preview (localhost unreachable) ──
        # Check once per session to avoid slow repeated probes
        if "_ollama_reachable" not in st.session_state:
            try:
                import requests

                r = requests.get("http://localhost:11434/api/tags", timeout=1.0)
                st.session_state._ollama_reachable = r.status_code == 200
            except Exception:
                st.session_state._ollama_reachable = False

        if _api_ui_mode:
            # Dynamically build the provider list — hide Ollama if unreachable
            # so cloud/preview users can't accidentally select it
            if st.session_state._ollama_reachable:
                _provider_options = ["Anthropic Claude", "DeepSeek API", "Ollama (Local)"]
            else:
                _provider_options = ["Anthropic Claude", "DeepSeek API"]
                # If previously selected Ollama but now unreachable, force reset
                if st.session_state.get("model_provider_sidebar") == "Ollama (Local)":
                    st.session_state["model_provider_sidebar"] = "Anthropic Claude"

            if st.session_state._ollama_reachable:
                model_provider = st.selectbox(
                    "Provider",
                    _provider_options,
                    key="model_provider_sidebar",
                    label_visibility="collapsed",
                )
            else:
                # Selectbox + tiny recheck icon in a compact row
                col_sel, col_btn = st.columns([5, 1])
                with col_sel:
                    model_provider = st.selectbox(
                        "Provider",
                        _provider_options,
                        key="model_provider_sidebar",
                        label_visibility="collapsed",
                    )
                with col_btn:
                    if st.button(
                        "🔄",
                        key="recheck_ollama",
                        help="重新检测本地 Ollama (启动 `ollama serve` 后点此)",
                    ):
                        st.session_state.pop("_ollama_reachable", None)
                        st.rerun()
        else:
            # End users should not see provider routing; owner controls it
            # via server-side env/secrets.
            model_provider = "Anthropic Claude"

        # API Key inputs based on provider
        import os

        _key_ok = False
        if not _api_ui_mode:
            # End-user mode: read keys from server env/secrets only,
            # never let user input. Show quota card instead.
            if _os_admin.environ.get("ANTHROPIC_API_KEY") or _safe_get_secret("ANTHROPIC_API_KEY"):
                st.session_state._model_provider = "Anthropic Claude"
                _key_ok = True
            elif _os_admin.environ.get("DEEPSEEK_API_KEY") or _safe_get_secret("DEEPSEEK_API_KEY"):
                st.session_state._model_provider = "DeepSeek API"
                _key_ok = True
            st.session_state._llm_configured = _key_ok

            # Plan + usage card
            try:
                from libs.auth.session import current_user
                from libs.billing.usage import get_quota_status

                _u = current_user()
                if _u:
                    _qs = get_quota_status(_u["id"])
                    st.caption(f"📋 Plan: **{_qs['label']}**")
                    _k = _qs["kinds"]
                    if "analysis" in _k and _k["analysis"]["limit"] is not None:
                        a = _k["analysis"]
                        st.caption(
                            f"📊 Analyses: **{a['used']}/{a['limit']}** this month"
                            + ("  ⚠️ exhausted" if a["exhausted"] else "")
                        )
                    if "chat" in _k and _k["chat"]["limit"] is not None:
                        c = _k["chat"]
                        st.caption(
                            f"💬 AI chats: **{c['used']}/{c['limit']}** this month"
                            + ("  ⚠️ exhausted" if c["exhausted"] else "")
                        )
                    if _qs["plan"] == "free":
                        st.caption(
                            "💡 Beta access: paid plans are configured but not live yet."
                            if current_lang == "en"
                            else "💡 Beta 阶段：付费计划已配置，但暂未正式开放。"
                        )
                else:
                    st.caption(
                        "🔐 Sign in to use free monthly AI credits."
                        if current_lang == "en"
                        else "🔐 登录后可使用每月免费 AI 额度。"
                    )
            except Exception:
                pass

        elif model_provider == "Anthropic Claude":
            api_key = st.text_input(
                "Claude API Key",
                type="password",
                value=os.environ.get("ANTHROPIC_API_KEY", "")
                or st.session_state.get("_api_key_input", ""),
                placeholder="sk-ant-...",
                key="claude_api_key_sidebar",
                help="从 https://console.anthropic.com/ 获取",
            )
            st.session_state._api_key_input = api_key
            _key_ok = bool(api_key and api_key.startswith("sk-"))

        elif model_provider == "DeepSeek API":
            deepseek_key = st.text_input(
                "DeepSeek API Key",
                type="password",
                value=os.environ.get("DEEPSEEK_API_KEY", "")
                or st.session_state.get("_deepseek_key", ""),
                placeholder="sk-...",
                key="deepseek_api_key_sidebar",
                help="从 https://platform.deepseek.com/ 获取",
            )
            st.session_state._deepseek_key = deepseek_key
            _key_ok = bool(deepseek_key and len(deepseek_key) > 10)

        elif model_provider == "Ollama (Local)":
            ollama_model = st.text_input(
                "Ollama Model",
                value=st.session_state.get("_ollama_model", "deepseek-r1:14b"),
                key="ollama_model_sidebar",
            )
            st.session_state._ollama_model = ollama_model
            _key_ok = st.session_state.get("_ollama_reachable", False)

        # Status indicator (admin mode only — non-admin already shows
        # a richer plan + quota card above)
        if _api_ui_mode:
            if _key_ok:
                st.caption(f"✅ {model_provider} 已配置")
            else:
                st.caption("⚠️ 请填写 API Key 以启用 AI 功能")

            # Store provider in session state (owner chose it)
            st.session_state._model_provider = model_provider
            st.session_state._llm_configured = _key_ok

        # ── FMP API key — hidden by default.
        # In end-user mode, FMP is server-controlled (set via env at deploy).
        if _api_ui_mode:
            _existing_fmp = (
                os.environ.get("FMP_API_KEY", "")
                or _safe_get_secret("FMP_API_KEY")
                or st.session_state.get("_fmp_key", "")
            )
            fmp_key_input = st.text_input(
                "FMP API Key (optional)",
                type="password",
                value=_existing_fmp,
                placeholder="your FMP key",
                key="fmp_api_key_sidebar",
                help=(
                    "Powers earnings transcripts, analyst price targets, and the "
                    "Institutional Analyst Report on the Ticker Research page. "
                    "Get a free key at https://site.financialmodelingprep.com/"
                ),
            )
            if fmp_key_input:
                st.session_state._fmp_key = fmp_key_input
                os.environ["FMP_API_KEY"] = fmp_key_input
                _looks_wrong = (
                    fmp_key_input.startswith("apify_")
                    or fmp_key_input.startswith("sk-")
                    or fmp_key_input.startswith("sk-ant-")
                    or len(fmp_key_input) < 20
                )
                if _looks_wrong:
                    st.caption("⚠️ 这不像 FMP key(可能粘错了)。")
                else:
                    st.caption("✅ FMP 已配置")
            else:
                st.caption("ℹ️ FMP 未配置")

        st.markdown("---")

        # Store current parameters in session state for app.py to access
        st.session_state.period_years = period_years
        st.session_state.mc_sims = mc_sims
        st.session_state.mc_horizon = mc_horizon
        st.session_state.market_shock = market_shock
        st.session_state.risk_free_fallback = risk_free_rate
        st.session_state.weights_input = weights_json

        # (Run Analysis button is now at the top — combined with Refresh Live Data)

        # ── Advanced Settings ─────────────────────────────────────
        with st.expander("🔧 Advanced"):
            col_lim1, col_lim2 = st.columns(2)
            with col_lim1:
                max_stock = st.number_input(
                    "Max Stock %",
                    min_value=5,
                    max_value=50,
                    value=15,
                    step=1,
                    key="max_stock_sidebar",
                )
            with col_lim2:
                max_sector = st.number_input(
                    "Max Sector %",
                    min_value=10,
                    max_value=100,
                    value=30,
                    step=5,
                    key="max_sector_sidebar",
                )

            st.session_state._risk_limits = {
                "max_single_stock_weight": max_stock / 100,
                "max_sector_weight": max_sector / 100,
            }

            # Enable margin monitoring
            enable_margin = st.checkbox(
                "Enable Margin Monitoring", value=False, key="enable_margin_sidebar"
            )
            st.session_state._enable_margin = enable_margin

        st.markdown("---")

        # ── Quick Actions ─────────────────────────────────────────
        with st.expander("⚡ Quick Actions"):
            if st.button("📋 Load Tech Portfolio", use_container_width=True):
                st.session_state.weights_json = json.dumps(
                    {
                        "AAPL": 0.20,
                        "GOOGL": 0.20,
                        "MSFT": 0.20,
                        "NVDA": 0.15,
                        "META": 0.15,
                        "TSLA": 0.10,
                    },
                    indent=2,
                )
                st.rerun()

            if st.button("🛡️ Load Balanced Portfolio", use_container_width=True):
                st.session_state.weights_json = json.dumps(
                    {"SPY": 0.40, "TLT": 0.20, "GLD": 0.15, "QQQ": 0.15, "IWM": 0.10}, indent=2
                )
                st.rerun()

            if st.button("🔥 Clear Cache", use_container_width=True):
                st.cache_data.clear()
                st.cache_resource.clear()
                st.success("Cache cleared!")

        # ── Footer ────────────────────────────────────────────────
        st.markdown("---")
        st.caption("MindMarket AI v3.0")
        st.caption("© 2024 Risk Analytics Platform")

    # Return language and translator for pages to use
    lang = current_lang
    t = get_translator(lang)
    return lang, t
