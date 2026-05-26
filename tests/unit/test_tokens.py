"""Tests for ui/tokens.py — the Fintech Dark design system.

The test suite is intentionally about CONTRACTS, not exact hex values:
the design team will iterate on the palette, but the load-bearing
attribute names + the shape of inline-style strings must stay stable
or the ~170 pages that template-format them will silently break.

What we DO pin:
  - Every backward-compat attribute exists and is a non-empty string.
  - New tokens (ai, shadow_ai, radius_card, font_display, ...) are
    present so new pages can rely on them.
  - Hex colours match the canonical 3- or 6-digit pattern.
  - Helper functions (glow, chip) round-trip a real ticker label.
"""

from __future__ import annotations

import re

import pytest

_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{3}(?:[0-9A-Fa-f]{3})?$")
_RGBA_RE = re.compile(r"^rgba\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*[\d.]+\s*\)$")


def _is_color_string(value: str) -> bool:
    """Either ``#aabbcc`` / ``#abc`` or ``rgba(r, g, b, a)``."""
    return bool(_HEX_RE.match(value) or _RGBA_RE.match(value))


# ── backward-compat attributes ──────────────────────────────────────


def test_token_backcompat_color_attributes_exist():
    """Every attribute that v2 callers depend on must keep its name."""
    from ui.tokens import T

    required = (
        "bg",
        "surface",
        "elevated",
        "hover",
        "border_subtle",
        "border_default",
        "border_strong",
        "text",
        "text_secondary",
        "text_muted",
        "text_link",
        "accent",
        "accent_bg",
        "positive",
        "positive_bg",
        "negative",
        "negative_bg",
        "warning",
        "warning_bg",
        "neutral",
        "neutral_bg",
    )
    for name in required:
        value = getattr(T, name, None)
        assert isinstance(value, str), f"{name} missing or not a string"
        assert _is_color_string(value), f"{name} = {value!r} is not a valid color"


def test_token_backcompat_typography_inline_styles():
    """v2 callers pass these directly into HTML style attrs. They must
    still be valid CSS declarations (``key:value`` pairs)."""
    from ui.tokens import T

    inline_style_attrs = (
        "font_page_title",
        "font_section",
        "font_subsection",
        "font_body",
        "font_label",
        "font_caption",
        "font_overline",
    )
    for name in inline_style_attrs:
        value = getattr(T, name)
        assert ":" in value, f"{name} must be a CSS declaration"
        assert "font-size:" in value, f"{name} should specify font-size"


def test_token_spacing_and_radius_are_px_strings():
    """v2 pages embed these into f-string ``padding:{T.sp_lg}`` etc.,
    so they need the px unit baked in."""
    from ui.tokens import T

    for name in ("sp_xs", "sp_sm", "sp_md", "sp_lg", "sp_xl", "sp_2xl"):
        value = getattr(T, name)
        assert value.endswith("px"), f"{name} = {value!r} should end with px"
    for name in ("radius", "radius_sm", "radius_lg"):
        value = getattr(T, name)
        assert value.endswith("px") or value == "9999px"


# ── new AI moat tokens ──────────────────────────────────────────────


def test_ai_palette_tokens_present():
    """Without these the moat UI in pages/1_Overview.py + the eventual
    React port can't reference the AI colour."""
    from ui.tokens import T

    assert _is_color_string(T.ai)
    assert _is_color_string(T.ai_secondary)
    assert _is_color_string(T.ai_bg)
    assert _is_color_string(T.ai_glow)


def test_new_radius_aliases_present():
    from ui.tokens import T

    for name in ("radius_chip", "radius_button", "radius_card", "radius_modal", "radius_pill"):
        assert isinstance(getattr(T, name), str)


def test_shadow_tokens_are_valid_box_shadow_strings():
    """Shadows are pasted into ``box-shadow:{...}`` so they need to be
    real box-shadow declarations (commas + 'rgba' + 'px')."""
    from ui.tokens import T

    for name in ("shadow_sm", "shadow_md", "shadow_ai", "shadow_loss", "shadow_gain"):
        value = getattr(T, name)
        assert isinstance(value, str)
        assert "px" in value, f"{name} = {value!r} should specify px offsets"
        assert "rgba(" in value, f"{name} should use rgba()"


def test_display_font_token_is_tabular_nums():
    """The hero number must be tabular-nums or the count-up animation
    will visibly shift horizontally."""
    from ui.tokens import T

    assert "tabular-nums" in T.font_display
    assert "font-size:56px" in T.font_display
    assert "font-weight:8" in T.font_display  # weight ≥ 800


# ── helper functions ────────────────────────────────────────────────


def test_glow_returns_valid_box_shadow_for_six_digit_hex():
    from ui.tokens import glow

    out = glow("#8B5CF6", alpha=0.30, radius_px=24)
    assert "rgba(139, 92, 246, 0.30)" in out
    assert "24px" in out


def test_glow_expands_three_digit_hex():
    from ui.tokens import glow

    out = glow("#F00")
    assert "rgba(255, 0, 0" in out


def test_glow_handles_hash_prefix_optional():
    from ui.tokens import glow

    assert "rgba(255, 0, 0" in glow("FF0000")


def test_chip_renders_inline_html_span_with_tone():
    from ui.tokens import T, chip

    out = chip("BUY", tone="gain")
    assert out.startswith("<span")
    assert "BUY" in out
    assert T.positive in out  # tone correctly mapped


def test_chip_unknown_tone_falls_back_to_neutral():
    from ui.tokens import T, chip

    out = chip("X", tone="not-a-real-tone")
    # Neutral uses text_secondary as the foreground colour.
    assert T.text_secondary in out


@pytest.mark.parametrize("tone", ["gain", "loss", "warning", "ai", "neutral"])
def test_chip_supports_every_documented_tone(tone):
    from ui.tokens import chip

    out = chip("X", tone=tone)
    assert "<span" in out


# ── inject_global_css contract ──────────────────────────────────────


def test_inject_global_css_emits_keyframes_and_fonts(monkeypatch):
    """Verify inject_global_css() actually renders the load-bearing
    keyframes + Google Fonts link. We patch Streamlit's ``markdown``
    to capture the emitted CSS without spinning up a real session."""
    import sys
    from unittest.mock import MagicMock

    fake_st = MagicMock()
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    sys.modules.pop("ui.components", None)
    import importlib

    components = importlib.import_module("ui.components")

    components.inject_global_css()
    fake_st.markdown.assert_called_once()
    css = fake_st.markdown.call_args.args[0]

    # The three keyframes are the load-bearing animations. If any of
    # them get accidentally dropped, the AI moat goes silent.
    for kf in ("mm-ai-breath", "mm-pulse-dot", "mm-score-rise"):
        assert f"@keyframes {kf}" in css, f"missing keyframe {kf}"

    # Inter must be preloaded — without it the body falls back to
    # the system font and tabular-nums isn't guaranteed.
    assert "Inter" in css
    assert "JetBrains+Mono" in css or "JetBrains Mono" in css
    assert "material-symbols" in css
    assert "Material Symbols Rounded" in css
    assert ".stApp p, .stApp span, .stApp div" not in css
    assert "display: flex !important;" not in css

    # Utility classes pages opt into.
    for cls in (".mm-ai-glow", ".mm-card", ".mm-pill", ".mm-mono", ".mm-display"):
        assert cls in css, f"utility class {cls} missing"
