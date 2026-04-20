"""
ui/shared_sidebar.py
Shared Sidebar Component - Displays consistently across all pages
"""

import streamlit as st
import json
import os
from i18n import get_translator


def _safe_get_secret(key):
    """Safely get secret from Streamlit secrets"""
    try:
        return st.secrets.get(key, "")
    except Exception:
        return ""


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
                lang = st.session_state.get("_lang", "en")
                return lang, get_translator(lang)
            st.session_state["_sidebar_run_id"] = _run_id
    except Exception:
        pass  # If we can't detect duplicate, just render

    # Get current language from session state
    current_lang = st.session_state.get("_lang", "en")

    with st.sidebar:
        # ── Logo and Title ────────────────────────────────────────
        st.markdown("""
        <div style="text-align: center; padding: 20px 0 10px 0;">
            <div style="font-size: 28px; font-weight: 800; color: #0B7285; letter-spacing: -0.5px;">
                MindMarket AI
            </div>
            <div style="color: #8B949E; font-size: 11px; font-weight: 500; letter-spacing: 1px; margin-top: 4px;">
                PORTFOLIO RISK ANALYTICS
            </div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("---")

        # ── Language Toggle ───────────────────────────────────────
        _lang_choice = st.radio(
            "Language",
            ["EN", "CN"],
            horizontal=True,
            label_visibility="collapsed",
            key="lang_toggle_sidebar"
        )
        new_lang = "zh" if _lang_choice == "CN" else "en"
        if new_lang != st.session_state.get("_lang", "en"):
            st.session_state._lang = new_lang
            st.rerun()

        st.markdown("---")

        # ── Portfolio Configuration ───────────────────────────────
        st.markdown("### 📊 Portfolio")

        # Combined Refresh + Run button (replaces separate Refresh and Run Analysis)
        _run_label_live = "🚀 Refresh & Run Analysis" if current_lang == "en" else "🚀 刷新并运行分析"
        if st.button(_run_label_live, type="primary", use_container_width=True, key="refresh_and_run"):
            try:
                import importlib
                import yfinance as yf
                import portfolio_config as _pc
                importlib.reload(_pc)
                PORTFOLIO_HOLDINGS = _pc.PORTFOLIO_HOLDINGS
                MARGIN_LOAN = _pc.MARGIN_LOAN
                from logging_config import get_logger

                logger = get_logger(__name__)
                logger.info("ui.button.refresh_and_run_clicked")

                def _shares(t):
                    h = PORTFOLIO_HOLDINGS[t]
                    return h['shares'] if isinstance(h, dict) else h

                with st.spinner("Fetching live prices..." if current_lang == "en" else "获取实时价格..."):
                    tickers = list(PORTFOLIO_HOLDINGS.keys())
                    data = yf.download(tickers, period="5d", progress=False)
                    current_prices = {}
                    for tk in tickers:
                        try:
                            if isinstance(data.columns, __import__('pandas').MultiIndex):
                                if tk in data['Close'].columns:
                                    price = data['Close'][tk].dropna().iloc[-1]
                                    current_prices[tk] = float(price)
                            else:
                                price = data['Close'].dropna().iloc[-1]
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
                    cost_basis = getattr(_pc, "TOTAL_COST_BASIS", 0)
                    meta = {
                        "total_long": total_value,
                        "net_equity": net_equity,
                        "margin_loan": MARGIN_LOAN,
                        "leverage": total_value / net_equity if net_equity > 0 else float("inf"),
                        "missing": [t for t in tickers if t not in current_prices],
                        "cost_basis": cost_basis,
                        "total_pnl": net_equity - cost_basis if cost_basis > 0 else None,
                        "total_pnl_pct": (net_equity - cost_basis) / cost_basis if cost_basis > 0 else None,
                    }

                    st.session_state.weights_json = json.dumps(live_weights, indent=2)
                    st.session_state._portfolio_meta = meta
                    st.session_state._run_trigger = True
                    st.session_state.last_weights_json = None
                    logger.info("ui.refresh_and_run.success",
                                ticker_count=len(live_weights),
                                total_long=round(total_value, 2),
                                net_equity=round(net_equity, 2))
                    st.rerun()
            except Exception as e:
                st.error(f"Failed: {str(e)}")

        # Secondary "Run with current weights" — for when user edits JSON manually
        _run_label_current = "Run with Current Weights" if current_lang == "en" else "用当前权重运行"
        if st.button(_run_label_current, use_container_width=True, key="run_current_only"):
            st.session_state._run_trigger = True
            st.rerun()

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
                if current_lang == "en" else
                "清除分析缓存并重新计算。"
            ),
        ):
            st.session_state._force_refresh = True
            st.session_state._run_trigger = True
            st.rerun()

        # Portfolio Metadata (if available)
        if meta := getattr(st.session_state, "_portfolio_meta", None):
            st.caption(f"💰 Net Equity: ${meta.get('net_equity', meta['total_long']):,.0f}")
            st.caption(f"📈 Total Long: ${meta['total_long']:,.0f}")
            st.caption(f"🏦 Margin: ${meta.get('margin_loan', 0):,.0f}")
            st.caption(f"⚖️ Leverage: {meta['leverage']:.2f}x")
            if meta.get("cost_basis") and meta["cost_basis"] > 0:
                _pnl = meta.get("total_pnl", 0)
                _pnl_pct = meta.get("total_pnl_pct", 0)
                _pnl_icon = "🟢" if _pnl >= 0 else "🔴"
                st.caption(f"💵 Cost Basis: ${meta['cost_basis']:,.0f}")
                st.caption(f"{_pnl_icon} P&L: ${_pnl:+,.0f} ({_pnl_pct:+.1%})")

        # Initialize weights_json if not exists
        if "weights_json" not in st.session_state:
            st.session_state.weights_json = json.dumps({
                "AAPL": 0.4,
                "TSLA": 0.3,
                "BTC-USD": 0.3
            }, indent=2)

        # Handle example portfolio selection (from main page buttons)
        if "_example_portfolio" in st.session_state:
            st.session_state.weights_json = st.session_state._example_portfolio
            del st.session_state._example_portfolio

        # Weights Input
        st.caption("Weights (JSON)")
        weights_json = st.text_area(
            "Portfolio Weights",
            value=st.session_state.weights_json,
            height=120,
            label_visibility="collapsed"
        )

        st.markdown("---")

        # ── Analysis Parameters ───────────────────────────────────
        st.markdown("### ⚙️ Parameters")

        col1, col2 = st.columns(2)
        with col1:
            period_years = st.slider(
                "History (yr)",
                min_value=1,
                max_value=5,
                value=st.session_state.get("period_years", 2),
                key="period_years_sidebar"
            )

        with col2:
            mc_sims = st.select_slider(
                "MC Sims",
                options=[1000, 5000, 10000, 20000, 50000],
                value=st.session_state.get("mc_sims", 10000),
                key="mc_sims_sidebar"
            )

        col3, col4 = st.columns(2)
        with col3:
            mc_horizon = st.slider(
                "Horizon (d)",
                min_value=5,
                max_value=63,
                value=st.session_state.get("mc_horizon", 21),
                key="mc_horizon_sidebar"
            )

        with col4:
            market_shock_pct = st.slider(
                "Shock (%)",
                min_value=-30,
                max_value=0,
                value=int(st.session_state.get("market_shock", -0.10) * 100),
                key="market_shock_sidebar"
            )
            market_shock = market_shock_pct / 100

        # Risk-free rate
        risk_free_rate = st.number_input(
            "Risk-Free Rate (%)",
            min_value=0.0,
            max_value=15.0,
            value=4.5,
            step=0.1,
            key="risk_free_rate_sidebar"
        ) / 100

        st.markdown("---")

        # ── AI Provider Configuration ─────────────────────────────
        st.markdown("### 🤖 AI Provider")

        # ── Detect if running in cloud/preview (localhost unreachable) ──
        # Check once per session to avoid slow repeated probes
        if "_ollama_reachable" not in st.session_state:
            try:
                import requests
                r = requests.get("http://localhost:11434/api/tags", timeout=1.0)
                st.session_state._ollama_reachable = r.status_code == 200
            except Exception:
                st.session_state._ollama_reachable = False

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
                label_visibility="collapsed"
            )
        else:
            # Selectbox + tiny recheck icon in a compact row
            col_sel, col_btn = st.columns([5, 1])
            with col_sel:
                model_provider = st.selectbox(
                    "Provider",
                    _provider_options,
                    key="model_provider_sidebar",
                    label_visibility="collapsed"
                )
            with col_btn:
                if st.button("🔄", key="recheck_ollama",
                             help="重新检测本地 Ollama (启动 `ollama serve` 后点此)"):
                    st.session_state.pop("_ollama_reachable", None)
                    st.rerun()

        # API Key inputs based on provider
        import os
        _key_ok = False
        if model_provider == "Anthropic Claude":
            api_key = st.text_input(
                "Claude API Key",
                type="password",
                value=os.environ.get("ANTHROPIC_API_KEY", "") or st.session_state.get("_api_key_input", ""),
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
                value=os.environ.get("DEEPSEEK_API_KEY", "") or st.session_state.get("_deepseek_key", ""),
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
                key="ollama_model_sidebar"
            )
            st.session_state._ollama_model = ollama_model
            _key_ok = st.session_state.get("_ollama_reachable", False)

        # Status indicator: green check if configured, red warning if not
        if _key_ok:
            st.caption(f"✅ {model_provider} 已配置")
        else:
            st.caption(f"⚠️ 请填写 API Key 以启用 AI 功能")

        # Store provider in session state
        st.session_state._model_provider = model_provider
        st.session_state._llm_configured = _key_ok

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
                    key="max_stock_sidebar"
                )
            with col_lim2:
                max_sector = st.number_input(
                    "Max Sector %",
                    min_value=10,
                    max_value=100,
                    value=30,
                    step=5,
                    key="max_sector_sidebar"
                )

            st.session_state._risk_limits = {
                "max_single_stock_weight": max_stock / 100,
                "max_sector_weight": max_sector / 100,
            }

            # Enable margin monitoring
            enable_margin = st.checkbox(
                "Enable Margin Monitoring",
                value=False,
                key="enable_margin_sidebar"
            )
            st.session_state._enable_margin = enable_margin

        st.markdown("---")

        # ── Quick Actions ─────────────────────────────────────────
        with st.expander("⚡ Quick Actions"):
            if st.button("📋 Load Tech Portfolio", use_container_width=True):
                st.session_state.weights_json = json.dumps({
                    "AAPL": 0.20,
                    "GOOGL": 0.20,
                    "MSFT": 0.20,
                    "NVDA": 0.15,
                    "META": 0.15,
                    "TSLA": 0.10
                }, indent=2)
                st.rerun()

            if st.button("🛡️ Load Balanced Portfolio", use_container_width=True):
                st.session_state.weights_json = json.dumps({
                    "SPY": 0.40,
                    "TLT": 0.20,
                    "GLD": 0.15,
                    "QQQ": 0.15,
                    "IWM": 0.10
                }, indent=2)
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
