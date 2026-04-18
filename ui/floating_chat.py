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


# ──────────────────────────────────────────────────────────────
#  Self-contained LLM call (avoids circular import with app.py)
# ──────────────────────────────────────────────────────────────
def _chat_call_llm(prompt: str, system: str = "", max_tokens: int = 600, temperature: float = 0.3) -> str:
    """
    Minimal LLM call that mirrors app.call_llm but lives in this module
    to avoid circular imports (app.py -> ui.floating_chat -> app.call_llm).
    Reads provider config from st.session_state set by shared_sidebar.
    """
    import time

    model_provider = st.session_state.get("_model_provider", "Ollama (Local)")
    api_key_input = st.session_state.get("_api_key_input", "")
    deepseek_key = st.session_state.get("_deepseek_key", "")
    ollama_model = st.session_state.get("_ollama_model", "deepseek-r1:14b")

    if model_provider == "Anthropic Claude" and api_key_input:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key_input)
        for attempt in range(3):
            try:
                resp = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=max_tokens,
                    system=system or "You are a helpful financial analyst.",
                    messages=[{"role": "user", "content": prompt}],
                )
                return resp.content[0].text.strip()
            except Exception as e:
                err_str = str(e).lower()
                if "overloaded" in err_str or "529" in err_str or "rate" in err_str:
                    if attempt < 2:
                        time.sleep(2 * (attempt + 1))
                        continue
                raise

    elif model_provider == "DeepSeek API" and deepseek_key:
        from openai import OpenAI
        client = OpenAI(api_key=deepseek_key, base_url="https://api.deepseek.com/v1")
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

    elif model_provider == "Ollama (Local)":
        import requests as _requests
        payload = {
            "model": ollama_model,
            "messages": [{"role": "user", "content": prompt}],
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
        "No LLM backend configured. Please set an API key in the sidebar "
        "(AI Provider section)."
    )


# ──────────────────────────────────────────────────────────────
#  Build portfolio context string from session_state
# ──────────────────────────────────────────────────────────────
def _build_portfolio_context() -> str:
    """Assemble a concise context block from whatever is in session_state."""
    parts = []

    weights = st.session_state.get("weights_input") or st.session_state.get("weights_json")
    if weights:
        parts.append(f"Current portfolio weights (JSON):\n{weights}")

    meta = st.session_state.get("_portfolio_meta")
    if meta:
        parts.append(
            f"Portfolio metadata: "
            f"Net Equity=${meta.get('net_equity', 0):,.0f}, "
            f"Total Long=${meta.get('total_long', 0):,.0f}, "
            f"Margin Loan=${meta.get('margin_loan', 0):,.0f}, "
            f"Leverage={meta.get('leverage', 0):.2f}x"
        )

    report = st.session_state.get("report")
    if report:
        parts.append(
            f"Latest risk report: "
            f"Annual Return={report.annual_return:.2%}, "
            f"Volatility={report.annual_volatility:.2%}, "
            f"Sharpe={report.sharpe_ratio:.2f}, "
            f"VaR95={report.var_95:.2%}, "
            f"CVaR95={report.cvar_95:.2%}, "
            f"Max Drawdown={report.max_drawdown:.2%}, "
            f"Stress Loss={report.stress_loss:.2%}"
        )
        if report.betas:
            top_beta = sorted(report.betas.items(), key=lambda x: abs(x[1]), reverse=True)[:5]
            parts.append("Top betas: " + ", ".join(f"{t}={b:.2f}" for t, b in top_beta))
        if report.component_var_pct is not None:
            try:
                cvar_items = sorted(
                    ((t, float(v)) for t, v in report.component_var_pct.items()),
                    key=lambda x: x[1], reverse=True,
                )[:5]
                parts.append(
                    "Top VaR contributors: " + ", ".join(f"{t}={v:.1%}" for t, v in cvar_items)
                )
            except Exception:
                pass

    if not parts:
        return "No portfolio data loaded yet. The user should run an analysis first."

    return "\n\n".join(parts)


_SYSTEM_PROMPT = (
    "You are a senior institutional portfolio risk analyst embedded in a risk "
    "dashboard app.  You have access to the user's live portfolio data shown "
    "below.  Answer questions concisely and authoritatively, citing specific "
    "numbers.  Use bullet points for clarity.  Keep answers to 3-5 sentences "
    "unless the user asks for more detail.\n\n"
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
@st.dialog("AI Risk Analyst", width="large")
def _open_chat_dialog():
    """Full chat experience inside a Streamlit modal dialog."""

    if "_fc_messages" not in st.session_state:
        st.session_state._fc_messages = []

    provider = st.session_state.get("_model_provider", "Ollama (Local)")
    st.caption(
        f"Powered by {provider}  --  "
        "Ask about your portfolio risk, market conditions, or strategy"
    )

    chat_container = st.container(height=420)
    with chat_container:
        if not st.session_state._fc_messages:
            st.markdown(
                "_No messages yet.  Type a question below or click a suggestion._"
            )
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

    col_clear, col_info = st.columns([1, 3])
    with col_clear:
        if st.button("Clear history", key="_fc_clear"):
            st.session_state._fc_messages = []
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

    context = _build_portfolio_context()
    system = _SYSTEM_PROMPT.format(context=context)

    recent = st.session_state._fc_messages[-10:]
    conversation_parts = []
    for msg in recent:
        role_label = "User" if msg["role"] == "user" else "Assistant"
        conversation_parts.append(f"{role_label}: {msg['content']}")
    full_prompt = "\n\n".join(conversation_parts)

    with chat_container:
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    response = _chat_call_llm(
                        prompt=full_prompt,
                        system=system,
                        max_tokens=800,
                        temperature=0.3,
                    )
                except ConnectionError as e:
                    response = (
                        f"**Connection Error:** {e}\n\n"
                        "Please check your AI provider settings in the sidebar."
                    )
                except ValueError as e:
                    response = f"**Configuration Error:** {e}"
                except Exception as e:
                    response = (
                        f"**Error:** {e}\n\n"
                        "Try again or switch AI provider in the sidebar."
                    )
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
    st.markdown(r"""
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
""", unsafe_allow_html=True)

    # ── Real clickable button inside a keyed Streamlit container ──
    with st.container(key="fc_trigger_wrap"):
        open_chat = st.button(
            "\U0001F4AC",
            key="_fc_open_btn",
            help="Open AI Chat Assistant",
        )

    if open_chat:
        _open_chat_dialog()
