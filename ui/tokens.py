"""ui/tokens.py — MindMarket AI design tokens.

Fintech Dark · v3 (2026-05-26)
==============================

Inspired by Robinhood (calm dark base + bright actionable accents),
Stripe Dashboard (typography + spacing), and Linear (motion + ambient
glow). The retired v2 enterprise palette (GitHub-dark style) is still
exported under every original attribute name, so callers across the
~170 files that import ``T.bg`` / ``T.text`` / ``T.accent`` etc.
continue to render — only the underlying hex values are refreshed.

Three product principles encoded here:

1. **Progressive disclosure**: tokens for "hero" sizes (font_display)
   plus calm "body" sizes (font_body). Pages use the hero size for the
   single number they want users to read first.
2. **Emotional design**: a deep ink-black base (#0A0B0F, NOT pure
   black — avoids OLED halo + eye strain), warm-white text, and three
   semantic accents (gain green / loss red / AI purple) tuned at the
   same perceived brightness so none visually dominates the others.
3. **Moat highlight**: a dedicated ``ai`` palette + ``shadow_ai``
   glow + a ready-to-use ``mm-ai-glow`` keyframe (defined in
   ``ui.components.inject_global_css``) so AI features have a
   recognisable visual signature distinct from gain/loss.

Usage::

    from ui.tokens import T
    st.markdown(
        f'<div style="background:{T.surface};border-radius:{T.radius_card};'
        f'box-shadow:{T.shadow_md};padding:{T.sp_lg};">…</div>',
        unsafe_allow_html=True,
    )
"""


class T:
    """Centralised design tokens. Import as ``from ui.tokens import T``."""

    # ── Backgrounds ──────────────────────────────────────────────────
    # 0a/0b/0f → deep ink, not pure black (no OLED halo, no eye strain).
    # The three-step elevation lets us nest cards without ambiguity:
    #   bg     = page canvas
    #   surface= primary card
    #   elevated/hover = active / floating
    bg = "#0A0B0F"
    surface = "#1A1D27"
    elevated = "#232732"
    hover = "#232732"

    # ── Borders ─────────────────────────────────────────────────────
    # White-alpha so borders work on top of any surface — no
    # mismatched edges when we layer cards.
    border_subtle = "rgba(255, 255, 255, 0.04)"
    border_default = "rgba(255, 255, 255, 0.08)"
    border_strong = "rgba(255, 255, 255, 0.14)"

    # ── Text ────────────────────────────────────────────────────────
    # Warm white (#F5F6FA, NOT pure white) — softens glare on dark.
    text = "#F5F6FA"
    text_primary = "#F5F6FA"  # alias for new code
    text_secondary = "#B8BFCC"
    text_tertiary = "#8B95A7"  # new — for captions / hints
    text_muted = "#6E7689"
    text_disabled = "#424857"  # new
    text_link = "#8B5CF6"  # AI purple — clickable text doubles as moat colour

    # ── Brand Accent (teal, kept for back-compat) ──────────────────
    # Existing pages use `accent` for headers / overlines / dividers.
    # We keep the teal so those pages don't visually break, but new
    # AI-specific UI should use the `ai` palette below.
    accent = "#0B7285"
    accent_bg = "rgba(11, 114, 133, 0.12)"

    # ── AI moat palette (NEW) ───────────────────────────────────────
    # Reserved for AI Risk Copilot UI:
    #   - the breathing glow around the Health Score card
    #   - the "Ask AI" gradient button
    #   - any chip / pill marking AI-authored content
    # Distinct hue from gain/loss so a glance can tell "this came from
    # AI" without reading the label.
    ai = "#8B5CF6"
    ai_secondary = "#6366F1"
    ai_bg = "rgba(139, 92, 246, 0.12)"
    ai_glow = "rgba(139, 92, 246, 0.40)"

    # ── Semantic ────────────────────────────────────────────────────
    # Brighter than v2 — Fintech UI lives or dies on the contrast of
    # the gain/loss colour. Tuned so green + red + AI purple all sit
    # at the same perceived brightness on the #1A1D27 surface.
    positive = "#00D67D"
    positive_bg = "rgba(0, 214, 125, 0.12)"
    negative = "#FF4757"
    negative_bg = "rgba(255, 71, 87, 0.12)"
    warning = "#FFB627"
    warning_bg = "rgba(255, 182, 39, 0.12)"
    neutral = "#8B95A7"
    neutral_bg = "rgba(139, 149, 167, 0.10)"

    # ── Typography (inline styles for st.markdown injection) ───────
    # Existing pages pass these directly into HTML style attrs, e.g.
    # `<div style="{T.font_section};...">`. Don't change the inline-
    # style shape unless you're prepared to update every caller.
    font_page_title = "font-size:28px;font-weight:700;letter-spacing:-0.4px"
    font_section = "font-size:18px;font-weight:600;letter-spacing:-0.2px"
    font_subsection = "font-size:15px;font-weight:600"
    font_body = "font-size:14px;font-weight:500"
    font_label = "font-size:12px;font-weight:500"
    font_caption = "font-size:12px;font-weight:500"
    font_overline = "font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.18em"

    # Hero display style — for the Account Health Score / Hero KPI.
    # Use sparingly: ONE per page max.
    font_display = (
        "font-size:56px;font-weight:800;line-height:1;letter-spacing:-1px;"
        "font-variant-numeric:tabular-nums"
    )

    # Mono — for ticker symbols and small numeric badges. Pairs with
    # the JetBrains Mono import in inject_global_css().
    font_mono = (
        "font-family:'JetBrains Mono','SF Mono','Roboto Mono',Menlo,monospace;"
        "font-variant-numeric:tabular-nums"
    )

    # ── Spacing (4pt grid) ──────────────────────────────────────────
    sp_xs = "4px"
    sp_sm = "8px"
    sp_md = "12px"
    sp_lg = "16px"
    sp_xl = "24px"
    sp_2xl = "32px"
    sp_3xl = "48px"  # new — used on landing heroes

    # ── Radius ──────────────────────────────────────────────────────
    # 14px on cards = "modern but not cartoonish". 10px on buttons
    # matches Robinhood / Stripe; smaller would look enterprise-y.
    radius = "14px"  # canonical card radius (was 8px in v2)
    radius_sm = "8px"
    radius_lg = "20px"
    radius_chip = "6px"  # new — for inline pills / ticker chips
    radius_button = "10px"  # new
    radius_card = "14px"  # new — explicit alias
    radius_modal = "20px"  # new
    radius_pill = "9999px"  # new — for status pills

    # ── Shadows ─────────────────────────────────────────────────────
    # Three shadow levels, strictly scoped:
    #   shadow_sm   = card at rest (almost invisible, just separates)
    #   shadow_md   = card on hover / drawer
    #   shadow_ai   = AI moat glow (purple, breathing)
    #   shadow_loss = critical risk callout
    shadow_sm = "0 1px 2px rgba(0, 0, 0, 0.16)"
    shadow_md = "0 4px 16px rgba(0, 0, 0, 0.24), " "0 1px 2px rgba(0, 0, 0, 0.32)"
    shadow_ai = "0 0 32px rgba(139, 92, 246, 0.28), " "0 0 8px rgba(139, 92, 246, 0.18)"
    shadow_loss = "0 0 24px rgba(255, 71, 87, 0.22)"
    shadow_gain = "0 0 24px rgba(0, 214, 125, 0.20)"

    # ── Gauge / heatmap zones (kept for risk page) ─────────────────
    gauge_danger = "#3D1520"
    gauge_warning = "#3D2A15"
    gauge_safe = "#1A3025"

    # ── Bright signal colors for charts / sparklines ───────────────
    # Slightly different from the UI chrome `positive` / `negative`
    # because charts read better with marginally higher saturation.
    signal_positive = "#00D67D"
    signal_negative = "#FF4757"
    signal_neutral = "#FFB627"


# ── Convenience helpers (no business logic; pure formatting) ────────


def glow(hex_color: str, *, alpha: float = 0.28, radius_px: int = 32) -> str:
    """Build a box-shadow string for an arbitrary accent glow.

    Used when a page wants a one-off colored glow (e.g. tinting a card
    by sector) without minting a new shadow token::

        from ui.tokens import glow
        st.markdown(
            f'<div style="box-shadow:{glow("#FFB627")};...">',
            unsafe_allow_html=True,
        )
    """
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(ch * 2 for ch in hex_color)
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return f"0 0 {radius_px}px rgba({r}, {g}, {b}, {alpha:.2f})"


def chip(text: str, *, tone: str = "neutral") -> str:
    """Render a status pill inline. Returns a self-contained HTML span
    suitable for ``st.markdown(..., unsafe_allow_html=True)``.

    ``tone`` is one of ``"gain"``, ``"loss"``, ``"warning"``,
    ``"ai"``, ``"neutral"``.
    """
    tone_map = {
        "gain": (T.positive, T.positive_bg),
        "loss": (T.negative, T.negative_bg),
        "warning": (T.warning, T.warning_bg),
        "ai": (T.ai, T.ai_bg),
        "neutral": (T.text_secondary, T.neutral_bg),
    }
    color, background = tone_map.get(tone, tone_map["neutral"])
    return (
        f'<span style="display:inline-block;padding:2px 8px;'
        f"border-radius:{T.radius_pill};background:{background};"
        f"color:{color};{T.font_caption};font-weight:600;"
        f'letter-spacing:0.05em;">{text}</span>'
    )
