"""
ui/tokens.py
Design tokens for MindMarket AI.
Dark-mode-first enterprise SaaS design system.
Inspired by: Bloomberg Terminal, Linear, Stripe Dashboard, Ramp.
"""


class T:
    """Centralized design tokens. Import as: from ui.tokens import T"""

    # ── Backgrounds ──────────────────────────────────────────
    bg = "#0F1117"  # App background (near-black)
    surface = "#161B22"  # Card / panel surface
    elevated = "#1C2128"  # Popover, drawer, modal
    hover = "#21262D"  # Hover state

    # ── Borders ──────────────────────────────────────────────
    border_subtle = "rgba(139, 148, 158, 0.12)"
    border_default = "rgba(139, 148, 158, 0.20)"
    border_strong = "rgba(139, 148, 158, 0.35)"

    # ── Text ─────────────────────────────────────────────────
    text = "#E6EDF3"  # Primary (high contrast)
    text_secondary = "#8B949E"  # Labels, secondary
    text_muted = "#484F58"  # Disabled, tertiary
    text_link = "#58A6FF"  # Interactive

    # ── Brand Accent (single color) ──────────────────────────
    accent = "#0B7285"
    accent_bg = "rgba(11, 114, 133, 0.12)"

    # ── Semantic ─────────────────────────────────────────────
    positive = "#2EA043"
    positive_bg = "rgba(46, 160, 67, 0.10)"
    negative = "#DA3633"
    negative_bg = "rgba(218, 54, 51, 0.10)"
    warning = "#D29922"
    warning_bg = "rgba(210, 153, 34, 0.10)"
    neutral = "#8B949E"
    neutral_bg = "rgba(139, 148, 158, 0.08)"

    # ── Typography ───────────────────────────────────────────
    font_page_title = "font-size:24px;font-weight:600"
    font_section = "font-size:16px;font-weight:600"
    font_subsection = "font-size:14px;font-weight:500"
    font_body = "font-size:14px;font-weight:400"
    font_label = "font-size:12px;font-weight:500"
    font_caption = "font-size:11px;font-weight:400"
    font_overline = "font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:1px"

    # ── Spacing ──────────────────────────────────────────────
    sp_xs = "4px"
    sp_sm = "8px"
    sp_md = "12px"
    sp_lg = "16px"
    sp_xl = "24px"
    sp_2xl = "32px"

    # ── Radius ───────────────────────────────────────────────
    radius = "8px"
    radius_sm = "6px"
    radius_lg = "12px"

    # ── Gauge / heatmap zones (background-only, low saturation) ───
    gauge_danger = "#3D1520"  # dark red for danger zone band
    gauge_warning = "#3D2A15"  # dark amber for warning zone band
    gauge_safe = "#1A3025"  # dark green for safe zone band

    # ── Bright signal colors (for accent text on data tables / charts) ─
    # NOTE: Prefer `positive`/`negative` for UI chrome.
    # These are higher-saturation variants meant for small accents on charts.
    signal_positive = "#00C853"
    signal_negative = "#FF5252"
    signal_neutral = "#D29922"
