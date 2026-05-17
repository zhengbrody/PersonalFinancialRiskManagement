"""
ui/floating_chat.py
Floating AI Assistant Component -- Functional Chat Implementation.

Combines a pure-CSS floating button (position:fixed, glow animation) with a
Streamlit-native @st.dialog for the actual chat.  A real st.button is styled
and positioned via CSS to overlay the decorative glow circle.  Clicking it
opens a dialog with st.chat_message / st.chat_input backed by the configured
LLM (Anthropic Claude, DeepSeek API, or local Ollama).
"""

import streamlit as st

_CHAT_LANGUAGE_OPTIONS = {
    "English": "English",
    "Chinese": "Simplified Chinese",
    "Match my message": "the same language as the user's latest message",
}

# Token budgets for Claude chat. Set to "comfortable headroom for the
# Assessment / Evidence / Risks / Actions structured reply" + a margin
# for verbose tickers. The previous 350/500/800 caps routinely cut
# Claude off mid-Actions section because each AECRA section is ~80-120
# tokens — four short sections + filler easily exceeds 500 tokens.
#
# Routing note: the Haiku-vs-Sonnet split lives in `_chat_call_llm`
# at `max_tokens <= 700`. SHORT and FAST stay under 700 so casual
# chat keeps routing to Haiku 4.5 (TTFT ~300ms, throughput ~150 tok/s).
# DEEP intentionally crosses the threshold — multi-step scenarios /
# hedging questions are worth the slower Sonnet reasoning.
_SHORT_CHAT_MAX_TOKENS = 600
_FAST_CHAT_MAX_TOKENS = 700
_DEEP_CHAT_MAX_TOKENS = 1600
_MAX_CONTEXT_HOLDINGS = 15

# Keywords that flip "auto" depth classification to "deep". These are the
# kinds of questions where shipping a short context would make the answer
# either wrong (no factor betas to cite) or unhelpfully generic.
_DEEP_CONTEXT_KEYWORDS = (
    "var",
    "cvar",
    "hedge",
    "scenario",
    "stress",
    "beta",
    "factor",
    "drawdown",
    "allocation",
    "rebalance",
    "optimize",
    "regime",
    "exposure",
)
_DEEP_CONTEXT_LENGTH_THRESHOLD = 80


def _classify_context_depth(user_message: str) -> str:
    """Auto-classify a chat message as "short" or "deep" context.

    Heuristic: deep when the message is long (>80 chars) OR mentions any
    risk/scenario/hedging keyword. Otherwise short. Casual messages like
    "hi" or "what's NVDA" stay on the short path so we don't ship 1500
    tokens of factor betas just to greet the user.
    """
    text = (user_message or "").lower()
    if len(text) > _DEEP_CONTEXT_LENGTH_THRESHOLD:
        return "deep"
    for kw in _DEEP_CONTEXT_KEYWORDS:
        if kw in text:
            return "deep"
    return "short"


def _is_provider_auth_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "invalid x-api-key",
            "authentication_error",
            "invalid api key",
            "incorrect api key",
            "401",
        )
    )


def _mark_chat_dialog_closed():
    st.session_state._fc_dialog_open = False


def _response_budget(user_input: str, depth: str = "auto") -> int:
    """Pick the max_tokens budget for a chat response.

    Short questions (depth="short") get the smallest budget so Haiku can
    return quickly; deep-dive prompts get the larger budget. When depth is
    "auto" we fall back to the legacy keyword scan over ``user_input``.
    """
    if depth == "short":
        return _SHORT_CHAT_MAX_TOKENS
    if depth == "deep":
        return _DEEP_CHAT_MAX_TOKENS

    text = (user_input or "").lower()
    deep_markers = (
        "详细",
        "深入",
        "完整",
        "deep",
        "detailed",
        "full report",
        "step by step",
        "scenario",
        "hedge",
        "rebalance",
    )
    return (
        _DEEP_CHAT_MAX_TOKENS
        if any(marker in text for marker in deep_markers)
        else _FAST_CHAT_MAX_TOKENS
    )


def _call_deepseek(
    *,
    api_key: str,
    prompt: str,
    system: str,
    max_tokens: int,
    temperature: float,
) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com/v1")
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return resp.choices[0].message.content.strip()


# ──────────────────────────────────────────────────────────────
#  Self-contained LLM call (avoids circular import with app.py)
# ──────────────────────────────────────────────────────────────
def _chat_call_llm(
    prompt: str,
    system: str = "",
    max_tokens: int = 600,
    temperature: float = 0.3,
    stream: bool = False,
):
    """
    Minimal LLM call that mirrors app.call_llm but lives in this module
    to avoid circular imports (app.py -> ui.floating_chat -> app.call_llm).
    Reads provider config from st.session_state set by shared_sidebar.

    Quota: in non-admin mode, decrements the user's monthly chat counter.
    Admin mode (MINDMARKET_ADMIN_MODE=true) bypasses quota for local dev.

    When ``stream=True`` and the active provider is Anthropic Claude, this
    function returns a generator yielding text chunks (compatible with
    ``st.write_stream``). Non-Claude providers and error paths fall back to
    the standard synchronous str return (callers should handle both).
    """
    import os as _os
    import time

    try:
        _admin_secret = st.secrets.get("MINDMARKET_ADMIN_MODE", "")
    except Exception:
        _admin_secret = ""
    _admin_mode = str(
        _os.environ.get("MINDMARKET_ADMIN_MODE", "") or _admin_secret
    ).strip().lower() in ("1", "true", "yes", "on")

    model_provider = st.session_state.get("_model_provider", "Ollama (Local)")
    provider_slug = model_provider.lower().split()[0] if model_provider else None
    system_prompt = (
        system.strip()
        if system
        else (
            "You are a helpful financial analyst. Answer in English unless the "
            "caller explicitly requests another language."
        )
    )

    # Quota gate (production only).
    # Split-try pattern: imports in their OWN try/except so the ImportError
    # fail-open path is actually reachable. Combining them would NameError
    # on `except QuotaExceeded` when the import itself failed (the name is
    # an unbound local at that point), bypassing this whole branch.
    if not _admin_mode:
        try:
            from libs.auth.session import current_user
            from libs.billing.costs import estimate_llm_event
            from libs.billing.usage import (
                CostLimitExceeded,
                QuotaExceeded,
                check_and_consume,
            )
        except ImportError:
            # Billing module unavailable in this environment (e.g. running
            # the public demo from a fork without libs/billing wired).
            # Fail open ONLY for import errors — they reflect a deploy
            # configuration issue, not a user trying to spam free LLM calls.
            pass
        else:
            try:
                _u = current_user()
                if not _u:
                    return "🔐 Please sign in to use your free monthly AI chat credits."
                pending_ollama_model = st.session_state.get("_ollama_model", "deepseek-r1:14b")
                model_name = (
                    ("claude-haiku-4-5" if max_tokens <= 700 else "claude-sonnet-4-6")
                    if model_provider == "Anthropic Claude"
                    else (
                        "deepseek-chat"
                        if model_provider == "DeepSeek API"
                        else pending_ollama_model
                    )
                )
                usage_estimate = estimate_llm_event(
                    prompt=prompt,
                    system=system_prompt,
                    provider=provider_slug,
                    model=model_name,
                    max_tokens=max_tokens,
                )
                check_and_consume(
                    _u["id"],
                    "chat",
                    provider=provider_slug,
                    model=model_name,
                    tokens_in=int(usage_estimate["tokens_in"]),
                    tokens_out=int(usage_estimate["tokens_out"]),
                    cost_usd=float(usage_estimate["cost_usd"]),
                    metadata={
                        "feature": "floating_chat",
                        "estimated": usage_estimate["estimated"],
                        "max_tokens": max_tokens,
                    },
                )
            except QuotaExceeded as _qe:
                return (
                    f"⚠️ {_qe}\n\n"
                    "💡 Paid plans are configured but not live yet. Email "
                    "[contact@mindmarket.app](mailto:contact@mindmarket.app) "
                    "for beta access."
                )
            except CostLimitExceeded as _ce:
                return (
                    f"⚠️ {_ce}\n\n"
                    "💡 Owner spend guardrails are active. Email "
                    "[contact@mindmarket.app](mailto:contact@mindmarket.app) "
                    "for beta access."
                )
            except Exception as _quota_err:
                # Any other failure (Supabase outage, transient HTTP error)
                # fails CLOSED: we'd rather show the user an error than
                # silently grant free LLM calls.
                import logging as _logging

                _logging.getLogger(__name__).warning(
                    "floating_chat.quota_gate_failed", exc_info=_quota_err
                )
                return (
                    "⚠️ The quota service is temporarily unavailable, so we "
                    "can't process your chat right now. Please retry in a "
                    "minute. If this keeps happening, email "
                    "[contact@mindmarket.app](mailto:contact@mindmarket.app)."
                )

    # Server-controlled keys when not admin
    api_key_input = (
        (_os.environ.get("ANTHROPIC_API_KEY", "") or st.session_state.get("_api_key_input", ""))
        if not _admin_mode
        else st.session_state.get("_api_key_input", _os.environ.get("ANTHROPIC_API_KEY", ""))
    )
    deepseek_key = (
        (_os.environ.get("DEEPSEEK_API_KEY", "") or st.session_state.get("_deepseek_key", ""))
        if not _admin_mode
        else st.session_state.get("_deepseek_key", _os.environ.get("DEEPSEEK_API_KEY", ""))
    )
    ollama_model = st.session_state.get("_ollama_model", "deepseek-r1:14b")

    if model_provider == "Anthropic Claude" and api_key_input:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key_input)
        claude_model = "claude-haiku-4-5" if max_tokens <= 700 else "claude-sonnet-4-6"

        if stream:
            # Streaming branch — return a generator so the caller can
            # render tokens via st.write_stream(). TTFT drops from
            # 3-8s (waiting for the full response) to ~300ms.
            #
            # Truncation guard: after the stream ends, inspect
            # `stop_reason` from the final message. Claude returns
            # "end_turn" for a complete reply, "max_tokens" when it ran
            # out of budget, "stop_sequence" for matched stop tokens.
            # If we hit "max_tokens" the user just saw a sentence cut
            # mid-word — yield an explicit "[…truncated]" hint so they
            # know they can ask for more rather than wondering if the
            # network broke.
            def _stream_chunks():
                try:
                    with client.messages.stream(
                        model=claude_model,
                        max_tokens=max_tokens,
                        system=system_prompt,
                        messages=[{"role": "user", "content": prompt}],
                    ) as s:
                        for text in s.text_stream:
                            yield text
                        try:
                            final = s.get_final_message()
                            stop_reason = getattr(final, "stop_reason", None)
                            if stop_reason == "max_tokens":
                                yield (
                                    "\n\n_…(response hit the token budget — "
                                    "ask a follow-up like 'continue' or "
                                    "'expand on the Actions section' for more)_"
                                )
                        except Exception:
                            # final-message accessor isn't critical; if
                            # it fails, the streamed text is still valid.
                            pass
                except Exception as e:
                    if _is_provider_auth_error(e):
                        yield (
                            "\n\n**Configuration Error:** Claude API key was rejected. "
                            "Ask the site owner to rotate ANTHROPIC_API_KEY."
                        )
                    else:
                        yield f"\n\n**Error:** {e}"

            return _stream_chunks()

        for attempt in range(3):
            try:
                resp = client.messages.create(
                    model=claude_model,
                    max_tokens=max_tokens,
                    system=system_prompt,
                    messages=[{"role": "user", "content": prompt}],
                )
                return resp.content[0].text.strip()
            except Exception as e:
                err_str = str(e).lower()
                if _is_provider_auth_error(e):
                    if deepseek_key:
                        try:
                            fallback = _call_deepseek(
                                api_key=deepseek_key,
                                prompt=prompt,
                                system=system_prompt,
                                max_tokens=max_tokens,
                                temperature=temperature,
                            )
                        except Exception as deepseek_exc:
                            if _is_provider_auth_error(deepseek_exc):
                                raise ValueError(
                                    "Claude and DeepSeek are both unavailable because "
                                    "their server-side API keys were rejected. Please "
                                    "update ANTHROPIC_API_KEY and DEEPSEEK_API_KEY in "
                                    "the deployment secrets."
                                ) from deepseek_exc
                            raise
                        return (
                            "Note: Claude is temporarily unavailable because the "
                            "server-side Anthropic key was rejected. Answered via "
                            "DeepSeek instead.\n\n" + fallback
                        )
                    raise ValueError(
                        "Claude is not available because the server-side Anthropic "
                        "API key was rejected. Please update ANTHROPIC_API_KEY in "
                        "the deployment secrets, or use DeepSeek while Claude is fixed."
                    )
                if "overloaded" in err_str or "529" in err_str or "rate" in err_str:
                    if attempt < 2:
                        time.sleep(2 * (attempt + 1))
                        continue
                raise

    elif model_provider == "DeepSeek API" and deepseek_key:
        try:
            return _call_deepseek(
                api_key=deepseek_key,
                prompt=prompt,
                system=system_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as e:
            if _is_provider_auth_error(e):
                raise ValueError(
                    "DeepSeek is not available because the server-side API key "
                    "was rejected. Please update DEEPSEEK_API_KEY in the "
                    "deployment secrets."
                ) from e
            raise

    elif model_provider == "Ollama (Local)":
        import requests as _requests

        messages = [{"role": "system", "content": system_prompt}]
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": ollama_model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        try:
            resp = _requests.post("http://localhost:11434/api/chat", json=payload, timeout=60)
            resp.raise_for_status()
            return resp.json()["message"]["content"].strip()
        except Exception:
            raise ConnectionError(
                "Cannot connect to local Ollama (localhost:11434). "
                "Please make sure Ollama is running, or switch to DeepSeek / Claude API in the sidebar."
            )

    raise ValueError(
        "No LLM backend configured. Ask the site owner to configure server-side AI keys."
    )


# ──────────────────────────────────────────────────────────────
#  Build portfolio context string from session_state
# ──────────────────────────────────────────────────────────────
def _build_portfolio_context(*, depth: str = "auto", user_message: str = "") -> str:
    """Build the LLM context for the floating chat.

    depth:
        "short"  -- weights + net equity + top 3 holdings only (~300 tokens)
        "deep"   -- everything we have (~1500 tokens)
        "auto"   -- classify from ``user_message``: short for casual questions
                    ("hi", "what's NVDA"), deep for risk/scenario keywords.

    Auto-classification heuristic: deep when ``user_message`` length > 80 OR
    contains any of: var, cvar, hedge, scenario, stress, beta, factor,
    drawdown, allocation, rebalance, optimize, regime, exposure.
    """
    import json

    if depth == "auto":
        depth = _classify_context_depth(user_message)
    if depth not in ("short", "deep"):
        depth = "short"

    parts = []

    weights = st.session_state.get("weights") or {}
    if not weights:
        raw_weights = st.session_state.get("weights_input") or st.session_state.get("weights_json")
        if raw_weights:
            try:
                weights = json.loads(raw_weights)
            except Exception:
                weights = {}

    holdings = {}
    margin_loan = None
    portfolio_meta = {}
    if weights or st.session_state.get("analysis_ready"):
        try:
            from libs.auth.active_portfolio import (
                get_active_holdings,
                get_active_margin_loan,
                get_active_portfolio_meta,
            )

            holdings = get_active_holdings() or {}
            margin_loan = float(get_active_margin_loan() or 0)
            portfolio_meta = get_active_portfolio_meta() or {}
        except Exception:
            holdings = {}
            portfolio_meta = {}

    # Short depth caps the weights at the top 3 holdings; deep keeps the
    # full top-20 list so factor / concentration questions can be answered.
    weights_cap = 3 if depth == "short" else 20
    if weights:
        weight_items = sorted(
            ((str(t).upper(), float(w)) for t, w in weights.items()),
            key=lambda item: item[1],
            reverse=True,
        )
        parts.append(
            "Current portfolio weights:\n"
            + "\n".join(
                f"- {ticker}: {weight:.2%}" for ticker, weight in weight_items[:weights_cap]
            )
        )

    holdings_cap = 3 if depth == "short" else _MAX_CONTEXT_HOLDINGS
    if holdings:
        latest_prices = {}
        prices = st.session_state.get("prices")
        try:
            if prices is not None and not prices.empty:
                last_row = prices.ffill().iloc[-1]
                latest_prices = {str(k).upper(): float(v) for k, v in last_row.items()}
        except Exception:
            latest_prices = {}

        holding_rows = []
        total_cost = 0.0
        total_market_value = 0.0
        for ticker, holding in sorted(holdings.items()):
            if not isinstance(holding, dict):
                continue
            shares = float(holding.get("shares") or 0)
            avg_cost = holding.get("avg_cost")
            account = holding.get("account") or "default"
            asset_type = holding.get("asset_type") or "unknown"
            sector = holding.get("sector") or ""
            price = latest_prices.get(str(ticker).upper())
            market_value = shares * price if price is not None else None
            if market_value is not None:
                total_market_value += market_value
            cost = shares * float(avg_cost) if avg_cost is not None else None
            if cost is not None:
                total_cost += cost
            weight = (
                float(weights.get(ticker, weights.get(str(ticker).upper(), 0))) if weights else 0.0
            )
            sort_value = market_value if market_value is not None else weight
            line = (
                "- "
                + str(ticker).upper()
                + f": shares={shares:g}"
                + (f", weight={weight:.2%}" if weights else "")
                + (f", last_price=${price:,.2f}" if price is not None else "")
                + (f", market_value=${market_value:,.0f}" if market_value is not None else "")
                + (f", avg_cost=${float(avg_cost):,.2f}" if avg_cost is not None else "")
                + f", account={account}, asset_type={asset_type}"
                + (f", sector={sector}" if sector else "")
            )
            holding_rows.append((sort_value or 0.0, line))
        holding_rows.sort(key=lambda row: row[0], reverse=True)
        holding_lines = [line for _, line in holding_rows[:holdings_cap]]
        omitted = max(0, len(holding_rows) - len(holding_lines))
        parts.append(
            "Active user portfolio holdings"
            + (
                f" ({portfolio_meta.get('name')}, source={portfolio_meta.get('source')})"
                if portfolio_meta
                else ""
            )
            + ":\n"
            + "\n".join(holding_lines)
            + (
                f"\n- ... {omitted} smaller positions omitted from chat context for speed."
                if omitted
                else ""
            )
        )
        if total_market_value or total_cost or margin_loan is not None:
            parts.append(
                "Portfolio totals from holdings/prices: "
                f"market_value=${total_market_value:,.0f}, "
                f"known_cost_basis=${total_cost:,.0f}, "
                f"margin_loan=${float(margin_loan or 0):,.0f}"
            )

    # Recent FRED macroeconomic releases. Pulled via the shared helper so
    # the chat sees the same numbers as the page 8 table and the AI risk
    # briefing prompt. Failures are silenced -- the chat must keep working
    # if FRED is down. Only injected when the user actually has some
    # portfolio context to discuss (otherwise we want the "no portfolio
    # loaded yet" fallback to fire downstream). Skipped entirely for
    # "short" depth: macro releases + market state aren't relevant to
    # casual questions and they're the heaviest single context section.
    if parts and depth == "deep":
        # Current SPX + VIX level. Without these, Claude has no way to
        # answer "what if SPX drops to 7000" — it would have to GUESS
        # the current SPX level (we caught this on 2026-05-17, the LLM
        # made up "SPX ~7,778"). Cached at the yfinance layer.
        try:
            import yfinance as _yf

            spx_tk = _yf.Ticker("^GSPC")
            spx_hist = spx_tk.history(period="2d", auto_adjust=True)
            if not spx_hist.empty:
                spx_close = float(spx_hist["Close"].iloc[-1])
                spx_date = str(spx_hist.index[-1].date())
                spx_change = None
                if len(spx_hist) >= 2:
                    prev = float(spx_hist["Close"].iloc[-2])
                    spx_change = (spx_close - prev) / prev if prev else None
                line = f"- S&P 500 (^GSPC): {spx_close:,.2f} as of {spx_date}"
                if spx_change is not None:
                    line += f" ({spx_change:+.2%} d/d)"
                parts.append("Current market state:\n" + line)
        except Exception:
            pass

        try:
            from market_intelligence import fetch_10y_yield, fetch_macro_releases

            macro_rows = fetch_macro_releases() or []
            _ai_focus = {
                "CPIAUCSL",
                "CPILFESL",
                "PCEPI",
                "PCEPILFE",
                "FEDFUNDS",
                "UNRATE",
                "PAYEMS",
                "T10Y2Y",
            }
            # Skip DGS10 here — we replace it below with the fresher
            # yfinance ^TNX value so the LLM doesn't tell users a stale
            # T-1 close. Spread (T10Y2Y) stays on FRED, which is the
            # authoritative spread series.
            focused = [r for r in macro_rows if r.get("fred_id") in _ai_focus][:6]
            if not focused:
                focused = macro_rows[:5]
            macro_lines = []
            for row in focused:
                series = row.get("Series", "?")
                latest = row.get("Latest", "--")
                date = row.get("Date", "--")
                fred_id = row.get("fred_id", "")
                fred_tag = f" ({fred_id})" if fred_id else ""
                macro_lines.append(f"- {series}{fred_tag}: {latest} as of {date}")

            # 10Y Treasury yield: prefer yfinance ^TNX (intraday/EOD,
            # same-day) over FRED DGS10 (T-1, ~24h stale during US
            # trading hours). Both sources verified live 2026-05; see
            # the comment block above fetch_10y_yield in
            # market_intelligence.py. Wrapped defensively so any
            # transient failure (network, mock, cache) can't take down
            # the rest of the macro section.
            try:
                ten_y = fetch_10y_yield()
                if isinstance(ten_y, dict) and isinstance(ten_y.get("value"), (int, float)):
                    macro_lines.append(
                        f"- 10Y Treasury Yield: {float(ten_y['value']):.2f}% "
                        f"as of {ten_y.get('date', 'N/A')} "
                        f"(source: {ten_y.get('source', 'live')})"
                    )
            except Exception:
                pass

            if macro_lines:
                parts.append("Recent macro releases:\n" + "\n".join(macro_lines))
        except Exception:
            # FRED unreachable, dependency missing, etc. The chat
            # shouldn't fail just because we couldn't inject this
            # optional context.
            pass

    meta = st.session_state.get("_portfolio_meta")
    if meta:
        parts.append(
            f"Portfolio metadata: "
            f"Name={meta.get('portfolio_name', 'N/A')}, "
            f"Source={meta.get('portfolio_source', 'N/A')}, "
            f"Net Equity=${meta.get('net_equity', 0):,.0f}, "
            f"Total Long=${meta.get('total_long', 0):,.0f}, "
            f"Margin Loan=${meta.get('margin_loan', 0):,.0f}, "
            f"Leverage={meta.get('leverage', 0):.2f}x"
        )

    # The risk report block (Sharpe, VaR, CVaR, factor betas, component
    # VaR contributors) is the heaviest section and is only useful when
    # the user is actually asking risk-shaped questions. Skip on short.
    report = st.session_state.get("report") if depth == "deep" else None
    if report:
        try:
            from datetime import datetime

            last_ts = st.session_state.get("_last_analysis_ts")
            if last_ts:
                parts.append(
                    "Analysis freshness: latest risk run at "
                    + datetime.fromtimestamp(float(last_ts)).strftime("%Y-%m-%d %H:%M:%S")
                    + " local time."
                )
        except Exception:
            pass
        # Annotate stress_loss with its underlying scenario shock so the
        # LLM connects "stress_loss" to "what happens if the market drops
        # X%". Without this it was treating stress_loss as a vague number.
        try:
            shock_pct = float(st.session_state.get("market_shock") or -0.10)
            shock_label = f"under {shock_pct:+.0%} market shock"
        except Exception:
            shock_label = "under default market shock"
        parts.append(
            f"Latest risk report: "
            f"Annual Return={report.annual_return:.2%}, "
            f"Volatility={report.annual_volatility:.2%}, "
            f"Sharpe={report.sharpe_ratio:.2f}, "
            f"VaR95={report.var_95:.2%}, "
            f"CVaR95={report.cvar_95:.2%}, "
            f"Max Drawdown={report.max_drawdown:.2%}, "
            f"Stress Loss ({shock_label})={report.stress_loss:.2%}"
        )
        # Portfolio-weighted beta (when betas + weights are both present).
        # Useful proxy for scenario questions like "what if SPX drops X%":
        # estimated portfolio impact ≈ portfolio_beta × market_shock.
        try:
            betas = report.betas or {}
            weights_for_beta = st.session_state.get("weights") or {}
            if betas and weights_for_beta:
                total_w = sum(weights_for_beta.values()) or 1.0
                port_beta = sum(weights_for_beta.get(t, 0) * b for t, b in betas.items()) / total_w
                parts.append(
                    f"Portfolio-weighted beta (vs SPX): {port_beta:.2f} "
                    f"(estimate portfolio_pnl ≈ port_beta × market_move)."
                )
        except Exception:
            pass
        if report.betas:
            top_beta = sorted(report.betas.items(), key=lambda x: abs(x[1]), reverse=True)[:5]
            parts.append("Top betas: " + ", ".join(f"{t}={b:.2f}" for t, b in top_beta))
        if report.component_var_pct is not None:
            try:
                cvar_items = sorted(
                    ((t, float(v)) for t, v in report.component_var_pct.items()),
                    key=lambda x: x[1],
                    reverse=True,
                )[:5]
                parts.append(
                    "Top VaR contributors: " + ", ".join(f"{t}={v:.1%}" for t, v in cvar_items)
                )
            except Exception:
                pass

    if not parts:
        return (
            "No portfolio data is loaded yet. Ask the user to create/select a "
            "portfolio and run Refresh & Run Analysis before giving portfolio-specific advice."
        )

    return "\n\n".join(parts)


_SYSTEM_PROMPT = (
    "You are a senior institutional portfolio risk analyst embedded in MindMarket AI. "
    "You speak like a desk strategist briefing a PM: direct, numeric, decisive. "
    "Use only numbers from the PORTFOLIO CONTEXT below — never invent prices, "
    "returns, betas, VaR, or any other metric. "
    "\n\n"
    "RESPONSE RULES (these override anything that conflicts):\n"
    "1. Lead with the answer. NEVER open with 'I cannot' / 'I lack' / 'Without more "
    "information'. Use the data you DO have and give your best estimate. Caveats go "
    "at the END, in one short line.\n"
    "2. For scenario questions (e.g. 'if SPX drops to 7000'), compute the answer "
    "using the data in context: current SPX level, portfolio-weighted beta, stress_loss "
    "(which already encodes the market_shock scenario), margin ratios. Show the math "
    "in one line, then the result.\n"
    "3. Quote SPECIFIC numbers from the context — ticker symbols, exact percentages, "
    "dollar amounts. Generic phrasing ('your large-cap position') is not allowed.\n"
    "4. Structure: Assessment (1 line) · Evidence (2-4 bullets, with numbers) · "
    "Risks (2-3 bullets) · Actions (2-3 concrete moves). Skip a section only if "
    "nothing useful to say there.\n"
    "5. If a number is truly absent from context, label your estimate as such — e.g. "
    "'(estimated; portfolio beta not measured)' inline, NOT in a preamble. The user "
    "should still get a number.\n"
    "6. Do not add boilerplate disclaimers ('This is not investment advice') unless "
    "asked. The app shows that disclaimer in the legal footer already.\n"
    "\n"
    "Answer in {language}.\n\n"
    "--- PORTFOLIO CONTEXT ---\n{context}\n--- END CONTEXT ---"
)

_SUGGESTION_PROMPTS = [
    "What is my portfolio VaR and which asset contributes the most risk?",
    "Which holdings have the highest beta and how does that affect my risk?",
    "How is my sector concentration -- am I too exposed anywhere?",
    "What hedging strategies would reduce my drawdown risk?",
]


# ──────────────────────────────────────────────────────────────
#  The @st.dialog chat UI
# ──────────────────────────────────────────────────────────────
@st.dialog(
    "AI Risk Analyst",
    width="large",
    on_dismiss=_mark_chat_dialog_closed,
)
def _open_chat_dialog():
    """Full chat experience inside a Streamlit modal dialog."""

    if "_fc_messages" not in st.session_state:
        st.session_state._fc_messages = []

    provider = st.session_state.get("_model_provider", "Ollama (Local)")
    st.caption(
        f"Powered by {provider}  --  "
        "Ask about your portfolio risk, market conditions, or strategy"
    )

    st.selectbox(
        "Response language",
        list(_CHAT_LANGUAGE_OPTIONS.keys()),
        index=0,
        key="_fc_response_language",
        help="Only the chat assistant uses this language setting. The app UI stays English.",
    )

    chat_container = st.container(height=420)
    with chat_container:
        if not st.session_state._fc_messages:
            st.markdown("_No messages yet.  Type a question below or click a suggestion._")
        for msg in st.session_state._fc_messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    if not st.session_state._fc_messages:
        st.markdown("**Quick questions:**")
        cols = st.columns(2)
        for idx, suggestion in enumerate(_SUGGESTION_PROMPTS):
            with cols[idx % 2]:
                if st.button(suggestion, key=f"_fc_sug_{idx}", use_container_width=True):
                    _handle_user_input(suggestion, chat_container)

    user_input = st.chat_input(
        "Ask a question about your portfolio...",
        key="_fc_chat_input",
    )
    if user_input:
        _handle_user_input(user_input, chat_container)

    col_clear, col_close, col_info = st.columns([1, 1, 3])
    with col_clear:
        if st.button("Clear history", key="_fc_clear"):
            st.session_state._fc_messages = []
            st.rerun()
    with col_close:
        if st.button("Close", key="_fc_close"):
            _mark_chat_dialog_closed()
            st.rerun()
    with col_info:
        if st.session_state.get("analysis_ready"):
            st.caption("Analysis data loaded -- answers reference your portfolio.")
        else:
            st.caption("Run an analysis first for portfolio-aware answers.")


def _handle_user_input(user_input: str, chat_container):
    """Process a user message: append it, call LLM, append response, rerun."""
    st.session_state._fc_messages.append({"role": "user", "content": user_input})

    with chat_container:
        with st.chat_message("user"):
            st.markdown(user_input)

    # Tiered context: a one-word "hi" no longer ships 1500 tokens of
    # factor betas. Risk/scenario keywords (or long messages) flip to the
    # deep context that includes the full risk report + macro releases.
    depth = _classify_context_depth(user_input)
    context = _build_portfolio_context(depth=depth, user_message=user_input)
    language = _CHAT_LANGUAGE_OPTIONS.get(
        st.session_state.get("_fc_response_language", "English"),
        "English",
    )
    system = _SYSTEM_PROMPT.format(context=context, language=language)

    recent = st.session_state._fc_messages[-10:]
    conversation_parts = []
    for msg in recent:
        role_label = "User" if msg["role"] == "user" else "Assistant"
        conversation_parts.append(f"{role_label}: {msg['content']}")
    full_prompt = "\n\n".join(conversation_parts)

    max_tokens = _response_budget(user_input, depth=depth)
    provider = st.session_state.get("_model_provider", "")
    # Stream only Claude — DeepSeek/Ollama branches already use single-shot
    # HTTP and rewriting them would touch billing/quota plumbing we don't
    # want to disturb in this perf pass.
    use_stream = provider == "Anthropic Claude"

    response = ""
    with chat_container:
        with st.chat_message("assistant"):
            try:
                if use_stream:
                    stream_iter = _chat_call_llm(
                        prompt=full_prompt,
                        system=system,
                        max_tokens=max_tokens,
                        temperature=0.15,
                        stream=True,
                    )
                    # st.write_stream renders tokens as they arrive AND
                    # returns the concatenated final string for us to
                    # persist into the chat history.
                    response = st.write_stream(stream_iter) or ""
                else:
                    with st.spinner("Thinking..."):
                        response = _chat_call_llm(
                            prompt=full_prompt,
                            system=system,
                            max_tokens=max_tokens,
                            temperature=0.15,
                        )
                    st.markdown(response)
            except ConnectionError as e:
                response = (
                    f"**Connection Error:** {e}\n\n"
                    "Please check your AI provider settings in the sidebar."
                )
                st.markdown(response)
            except ValueError as e:
                response = f"**Configuration Error:** {e}"
                st.markdown(response)
            except Exception as e:
                response = f"**Error:** {e}\n\n" "Try again or switch AI provider in the sidebar."
                st.markdown(response)

    st.session_state._fc_messages.append({"role": "assistant", "content": response})
    st.rerun()


# ──────────────────────────────────────────────────────────────
#  Public entry point
# ──────────────────────────────────────────────────────────────
def render_floating_ai_chat():
    """
    Render the floating AI chat button and wire it to a functional dialog.

    How it works:
    1. A real st.button is placed inside st.container(key="fc_trigger_wrap").
       Streamlit >= 1.37 adds a CSS class ``st-key-fc_trigger_wrap`` to the
       container div, so we can reliably target it with CSS.
    2. CSS positions the container (and the button within it) as a fixed
       circular button at the bottom-right of the viewport.
    3. A decorative glow animation is achieved via box-shadow on the button
       itself (no separate overlay div needed).
    4. Clicking the button opens a @st.dialog with full chat functionality.

    Previous approach (broken): used st.markdown to inject raw <div> open/close
    tags around the button.  Streamlit renders each widget in its own container,
    so the button was never a child of the wrapper div, and the CSS selectors
    never matched -- making the button unclickable.
    """

    # ── CSS targets the keyed container via .st-key-fc_trigger_wrap ──
    st.markdown(
        r"""
<style>
/* Position the real Streamlit container at bottom-right */
.st-key-fc_trigger_wrap {
    position: fixed !important;
    bottom: 24px !important;
    right: 24px !important;
    z-index: 999999 !important;
    width: 64px !important;
    height: 64px !important;
}
/* Hide the default vertical-block gap/padding inside the container */
.st-key-fc_trigger_wrap [data-testid="stVerticalBlockBorderWrapper"] {
    background: none !important;
    border: none !important;
    padding: 0 !important;
}
.st-key-fc_trigger_wrap [data-testid="stVerticalBlock"] {
    gap: 0 !important;
}
/* Style the st.button inside the container into a matching circle */
.st-key-fc_trigger_wrap .stButton > button {
    width: 64px !important;
    height: 64px !important;
    min-height: 0 !important;
    border-radius: 50% !important;
    background: linear-gradient(135deg, #0B7285 0%, #00C8DC 100%) !important;
    border: none !important;
    color: white !important;
    font-size: 26px !important;
    padding: 0 !important;
    box-shadow: 0 4px 16px rgba(11, 114, 133, 0.4) !important;
    cursor: pointer !important;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
    line-height: 1 !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    animation: fc-glow 3s ease-in-out infinite !important;
}
@keyframes fc-glow {
    0%, 100% { box-shadow: 0 4px 16px rgba(11, 114, 133, 0.4); }
    50%      { box-shadow: 0 4px 24px rgba(0, 200, 220, 0.6); }
}
.st-key-fc_trigger_wrap .stButton > button:hover {
    transform: scale(1.08) translateY(-2px) !important;
    box-shadow: 0 8px 24px rgba(11, 114, 133, 0.6) !important;
    animation: none !important;
}
.st-key-fc_trigger_wrap .stButton > button:active {
    transform: scale(0.95) !important;
}
.st-key-fc_trigger_wrap .stButton > button p {
    font-size: 26px !important;
    margin: 0 !important;
    line-height: 1 !important;
}

@media (max-width: 768px) {
    .st-key-fc_trigger_wrap {
        width: 56px !important; height: 56px !important;
        bottom: 20px !important; right: 20px !important;
    }
    .st-key-fc_trigger_wrap .stButton > button {
        width: 56px !important; height: 56px !important;
    }
}
</style>
""",
        unsafe_allow_html=True,
    )

    # ── Real clickable button inside a keyed Streamlit container ──
    with st.container(key="fc_trigger_wrap"):
        open_chat = st.button(
            "\U0001f4ac",
            key="_fc_open_btn",
            help="Open AI Chat Assistant",
        )

    # Persist open state across reruns. st.chat_input + st.rerun() inside
    # _handle_user_input cause the script to re-execute; without a sticky
    # flag, `open_chat` is False on the rerun and the modal vanishes after
    # every question (user has to click the button again).
    if open_chat:
        st.session_state._fc_dialog_open = True

    if st.session_state.get("_fc_dialog_open"):
        _open_chat_dialog()
