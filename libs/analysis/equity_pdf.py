"""Institutional-grade PDF report builder for the equity analysis flow.

We use ``fpdf2`` (already a project dep) rather than WeasyPrint /
ReportLab for three reasons:

  - **Deterministic**. No browser / CSS engine, no font-fetching surprises.
  - **Stateless server-side**. The PDF is built from the in-memory
    ``DeepAnalysis`` + dossier, then returned as bytes for
    ``st.download_button`` — no temp files, no Lambda layer required.
  - **Already in production** (see ``report_generator.py``). Reusing a
    proven dep avoids a new attack surface.

The PDF layout, top-to-bottom:

    Page 1   Title block + verdict ribbon + one-paragraph thesis +
             the 5-dimension score card.
    Page 2   Fundamentals + Valuation tables, side by side.
    Page 3   Growth + Technicals tables, with catalysts list below.
    Page 4   Sentiment + Insider + Ownership, plus risks list.
    Page 5   Data gaps appendix + analyst meta (timestamp, dossier
             completeness, "what would change my mind").

Public API
----------
- ``build_equity_pdf(dossier, analysis)`` → ``bytes``.

The function NEVER raises on missing fields. Anything absent renders as
``—`` so the report ships even on a partial fetch.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime
from typing import Any

from .equity_research import DeepAnalysis, DimensionAssessment

_logger = logging.getLogger(__name__)


# ── color + style constants ────────────────────────────────────────


_INK = (16, 19, 26)  # main text
_INK_SOFT = (90, 99, 112)  # secondary text
_ACCENT = (11, 114, 133)  # MindMarket teal
_POSITIVE = (16, 160, 110)
_NEGATIVE = (217, 75, 75)
_WATCH = (217, 152, 60)
_BORDER = (220, 224, 230)
_CARD_BG = (247, 249, 250)

_RATING_COLOR = {
    "STRONG_BUY": _POSITIVE,
    "BUY": _POSITIVE,
    "HOLD": _ACCENT,
    "REDUCE": _WATCH,
    "AVOID": _NEGATIVE,
}

_CONF_COLOR = {
    "high": _POSITIVE,
    "medium": _WATCH,
    "low": _NEGATIVE,
}


# ── formatting helpers ────────────────────────────────────────────


def _dash() -> str:
    return "—"


def _fmt_pct(v: Any, *, signed: bool = False, places: int = 1) -> str:
    if v is None:
        return _dash()
    try:
        f = float(v)
    except (TypeError, ValueError):
        return _dash()
    fmt = f"{{:+.{places}%}}" if signed else f"{{:.{places}%}}"
    try:
        return fmt.format(f)
    except Exception:
        return _dash()


def _fmt_money(v: Any) -> str:
    if v is None:
        return _dash()
    try:
        f = float(v)
    except (TypeError, ValueError):
        return _dash()
    if abs(f) >= 1e9:
        return f"${f/1e9:,.2f}B"
    if abs(f) >= 1e6:
        return f"${f/1e6:,.2f}M"
    return f"${f:,.2f}"


def _fmt_num(v: Any, places: int = 2) -> str:
    if v is None:
        return _dash()
    try:
        f = float(v)
    except (TypeError, ValueError):
        return _dash()
    return f"{f:.{places}f}"


def _sanitize_text(value, *, unicode_safe: bool = False) -> str:
    """Coerce ``value`` into a string that fpdf2 can render.

    fpdf2 with the default Helvetica font supports only Latin-1, so
    we replace common typographic punctuation and then drop any
    remaining non-latin-1 glyphs. When a Unicode font has been
    registered on the PDF (``unicode_safe=True``) we keep CJK and
    other BMP characters intact — only the typographic replacement
    survives so the look stays consistent.
    """
    if value is None:
        return _dash()
    s = str(value)
    replacements = {
        "—": "-",
        "–": "-",
        "•": "*",
        "·": "-",
        " ": " ",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "…": "...",
        "→": "->",
        "±": "+/-",
    }
    for src_ch, dst_ch in replacements.items():
        s = s.replace(src_ch, dst_ch)
    if unicode_safe:
        return s
    return s.encode("latin-1", errors="replace").decode("latin-1")


def _safe(pdf, value) -> str:
    """Convenience wrapper that picks the right sanitiser mode based
    on whether ``pdf`` has a CJK font registered. All page composers
    should call this instead of ``_sanitize_text`` directly so a
    future Unicode-mode toggle stays consistent."""
    unicode_safe = bool(getattr(pdf, "_mm_cjk_font", None))
    return _sanitize_text(value, unicode_safe=unicode_safe)


# ── primitives layered on fpdf ────────────────────────────────────


def _new_pdf():
    """Lazy-import fpdf2 so test discovery doesn't require the dep.

    fpdf2 raises a friendly error if the dep is missing; we wrap that
    in a clearer one so the UI can surface "install fpdf2" instead of
    a generic import error.
    """
    try:
        from fpdf import FPDF
    except Exception as exc:  # pragma: no cover - dependency check
        raise RuntimeError(
            "fpdf2 is required for equity PDF export. "
            "It's already in requirements.txt — pip install -r requirements.txt."
        ) from exc

    class _DeepPDF(FPDF):
        """Subclass so we can add a consistent footer without touching
        every callsite.

        We also override ``set_font`` so every call to "Helvetica"
        transparently routes through the registered CJK font (if one is
        present). That spares every page composer from knowing whether
        CJK is active — they just call set_font with sensible weights /
        sizes, and Unicode rendering happens automatically when the
        font is available.
        """

        def set_font(self, family="", style="", size=0):  # type: ignore[override]
            cjk = getattr(self, "_mm_cjk_font", None)
            # fpdf2's CJK fonts often only define the regular weight
            # (no italic / bold variants registered separately), so we
            # ignore the style toggle in that case. Helvetica-styled
            # calls still produce a different visual weight via size.
            if cjk and (not family or family.lower() == "helvetica"):
                return super().set_font(cjk, "", size)
            return super().set_font(family, style, size)

        def footer(self):  # type: ignore[override]
            self.set_y(-12)
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(*_INK_SOFT)
            ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
            self.cell(
                0,
                6,
                _safe(
                    self,
                    f"MindMarket AI - Equity Research - Generated {ts} - Page {self.page_no()}",
                ),
                0,
                0,
                "C",
            )

    pdf = _DeepPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_title("MindMarket AI - Equity Research Report")
    pdf.set_author("MindMarket AI")
    pdf.set_creator("MindMarket AI Deep Analysis")
    return pdf


# ── CJK / Unicode font registration ────────────────────────────────
#
# fpdf2's default Helvetica is Latin-1 only — Chinese / Japanese text
# blows up. If the running environment has a CJK-capable TTF/TTC, we
# register it ONCE and use it for the whole PDF. Otherwise we keep the
# latin-1 sanitiser (replacement char for unrenderable glyphs).
#
# Search order:
#   1. Repo-local fonts/ directory (preferred, deterministic).
#   2. Common Linux production paths (Debian, Ubuntu, AL2023 with
#      google-noto-sans-cjk-fonts installed).
#   3. Common macOS dev paths (.ttc bundles).
#
# Set MINDMARKET_CJK_FONT_PATH to override.


_CJK_FONT_SEARCH_PATHS: tuple[str, ...] = (
    # Repo-local override (gitignored, devs add their own).
    "fonts/NotoSansSC-Regular.ttf",
    "fonts/NotoSansSC-Regular.otf",
    "fonts/cjk.ttf",
    # Common Linux production paths (Debian / Ubuntu / RHEL / AL2023).
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/google-noto-sans-cjk-fonts/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/wqy-microhei/wqy-microhei.ttc",
    "/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc",
    # macOS dev paths.
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
)


def _resolve_cjk_font() -> str | None:
    """Return a usable font path or ``None``. Pure-stat operation."""
    import os

    override = os.environ.get("MINDMARKET_CJK_FONT_PATH")
    if override and os.path.exists(override):
        return override
    for candidate in _CJK_FONT_SEARCH_PATHS:
        if os.path.exists(candidate):
            return candidate
    return None


def _register_cjk_font(pdf) -> str | None:
    """Register a CJK font on ``pdf`` and return its alias name, or
    ``None`` when no font is available (caller falls back to Helvetica
    + ASCII sanitiser).

    fpdf2's ``add_font(uni=True)`` is the magic that switches the PDF
    into Unicode mode. After that, ``set_font("MMCJK", ...)`` renders
    arbitrary BMP characters.

    On failure (font file unreadable, .ttc index issues), we log and
    return None — the PDF still ships with the legacy latin-1 path.
    """
    path = _resolve_cjk_font()
    if not path:
        return None
    try:
        # fpdf2 ≥ 2.5 deprecates the uni=True kwarg but still accepts
        # it; the modern path is to just call add_font and let the
        # library detect the TTF/TTC. Use that.
        pdf.add_font("MMCJK", "", path)
        return "MMCJK"
    except Exception as exc:
        _logger.warning("equity_pdf.cjk_font_register_failed path=%s err=%s", path, exc)
        return None


# ── Matplotlib chart helpers (PNG bytes) ──────────────────────────
#
# We render charts to PNG via matplotlib and embed with fpdf2.image().
# Matplotlib is a transitive dep (Plotly's static export depends on it
# too), so no requirements.txt churn. Each helper returns ``None`` if
# matplotlib fails to import or the input data is unusable — the page
# composer treats None as "skip the chart slot".
#
# Style: institutional grey, no clutter, single-axis. We deliberately
# avoid colour-coding to keep the report looking like a tearsheet
# rather than a marketing brochure.


def _fig_to_png_bytes(fig, *, width_in: float, height_in: float, dpi: int = 130) -> bytes | None:
    """Standard helper: size + save + close. Returns PNG bytes."""
    try:
        fig.set_size_inches(width_in, height_in)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", facecolor="white")
        buf.seek(0)
        return buf.read()
    finally:
        # Always close — long-running Streamlit sessions will leak
        # matplotlib figures otherwise.
        try:
            import matplotlib.pyplot as plt

            plt.close(fig)
        except Exception:
            pass


def _render_radar_png(analysis: DeepAnalysis) -> bytes | None:
    """Polar 5-axis radar of the dimension scores.

    Reads from ``analysis.dimensions`` directly — no extra data needed,
    so this chart is always renderable when the analysis exists.
    """
    try:
        import matplotlib
        import matplotlib.pyplot as plt
        import numpy as np
    except Exception:
        return None
    matplotlib.use("Agg", force=True)

    dims = ("quality", "fundamentals", "growth", "technicals", "sentiment")
    labels = ("Quality", "Fundamentals", "Growth", "Technicals", "Sentiment")
    scores: list[float] = []
    for k in dims:
        d = analysis.dimensions.get(k)
        scores.append(float(getattr(d, "score_0_100", 50) or 50))

    # Close the polygon by repeating the first value.
    angles = np.linspace(0, 2 * np.pi, len(dims), endpoint=False).tolist()
    angles += angles[:1]
    scores += scores[:1]

    try:
        fig, ax = plt.subplots(subplot_kw={"projection": "polar"})
        ax.set_facecolor("white")
        ax.plot(angles, scores, color="#0B7285", linewidth=2)
        ax.fill(angles, scores, color="#0B7285", alpha=0.18)
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(labels, fontsize=8, color="#5A6370")
        ax.set_yticks([20, 40, 60, 80, 100])
        ax.set_yticklabels(["20", "40", "60", "80", "100"], fontsize=6, color="#9099A6")
        ax.set_ylim(0, 100)
        ax.spines["polar"].set_color("#DCE0E6")
        ax.grid(color="#E8ECF1", linewidth=0.6)
        return _fig_to_png_bytes(fig, width_in=4.6, height_in=3.6)
    except Exception as exc:
        _logger.warning("equity_pdf.radar_render_failed err=%s", exc)
        return None


def _render_price_chart_png(price_history) -> bytes | None:
    """Render a 1y close price line chart with SMA50 / SMA200 overlays.

    ``price_history`` is a pandas Series (date-indexed, float). When
    None or shorter than 30 points we skip the chart.
    """
    try:
        import matplotlib
        import matplotlib.pyplot as plt
        import pandas as pd
    except Exception:
        return None
    matplotlib.use("Agg", force=True)

    if price_history is None:
        return None
    try:
        ser = pd.Series(price_history).dropna()
    except Exception:
        return None
    if ser.empty or len(ser) < 30:
        return None

    try:
        # Rolling means — only display when enough data points.
        sma50 = ser.rolling(50).mean() if len(ser) >= 50 else None
        sma200 = ser.rolling(200).mean() if len(ser) >= 200 else None

        fig, ax = plt.subplots()
        ax.plot(ser.index, ser.values, color="#101A20", linewidth=1.2, label="Close")
        if sma50 is not None:
            ax.plot(sma50.index, sma50.values, color="#0B7285", linewidth=1.0, label="SMA 50")
        if sma200 is not None:
            ax.plot(sma200.index, sma200.values, color="#D99840", linewidth=1.0, label="SMA 200")
        ax.set_facecolor("white")
        ax.set_ylabel("Price ($)", fontsize=8, color="#5A6370")
        ax.tick_params(axis="both", labelsize=7, colors="#5A6370")
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color("#DCE0E6")
        ax.grid(axis="y", color="#E8ECF1", linewidth=0.6)
        ax.legend(loc="upper left", fontsize=7, frameon=False)
        fig.autofmt_xdate(rotation=0, ha="center")
        return _fig_to_png_bytes(fig, width_in=6.5, height_in=2.8)
    except Exception as exc:
        _logger.warning("equity_pdf.price_chart_failed err=%s", exc)
        return None


def _embed_png(
    pdf,
    png_bytes: bytes | None,
    *,
    x: float | None = None,
    y: float | None = None,
    w: float = 0.0,
    h: float = 0.0,
) -> None:
    """Embed a PNG safely. No-op when bytes are None or fpdf2 refuses."""
    if not png_bytes:
        return
    try:
        buf = io.BytesIO(png_bytes)
        pdf.image(buf, x=x, y=y, w=w, h=h, type="PNG")
    except Exception as exc:
        _logger.warning("equity_pdf.embed_png_failed err=%s", exc)


def _set_color(pdf, rgb: tuple[int, int, int]) -> None:
    pdf.set_text_color(*rgb)


def _set_fill(pdf, rgb: tuple[int, int, int]) -> None:
    pdf.set_fill_color(*rgb)


def _set_border(pdf, rgb: tuple[int, int, int]) -> None:
    pdf.set_draw_color(*rgb)


def _hr(pdf, color: tuple[int, int, int] = _BORDER, w: float = 0.3) -> None:
    pdf.set_draw_color(*color)
    pdf.set_line_width(w)
    pdf.line(pdf.get_x(), pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(2)


def _section_header(pdf, label: str) -> None:
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 11)
    _set_color(pdf, _ACCENT)
    pdf.cell(0, 7, _safe(pdf, label.upper()), 0, 1)
    _hr(pdf, _ACCENT, 0.4)
    _set_color(pdf, _INK)
    pdf.set_font("Helvetica", size=10)


def _kv_table(pdf, rows: list[tuple[str, str]], *, col1: int = 60, col2: int = 35) -> None:
    """Two-column "Label / Value" table with subtle row striping."""
    pdf.set_font("Helvetica", size=9)
    for idx, (label, value) in enumerate(rows):
        if idx % 2 == 0:
            _set_fill(pdf, _CARD_BG)
        else:
            _set_fill(pdf, (255, 255, 255))
        _set_border(pdf, _BORDER)
        _set_color(pdf, _INK_SOFT)
        pdf.cell(col1, 6, _safe(pdf, label), border="LR", ln=0, fill=True)
        _set_color(pdf, _INK)
        pdf.cell(col2, 6, _safe(pdf, value), border="LR", ln=1, fill=True, align="R")
    # closing bottom border
    _set_border(pdf, _BORDER)
    pdf.cell(col1 + col2, 0, "", border="T", ln=1)
    _set_color(pdf, _INK)


def _bullet_list(pdf, items: list[str], *, max_items: int = 8) -> None:
    """Tight bullet list. Empty input prints '— none —'.

    Using multi_cell with the page's full content width (recomputed
    from the margins) so wrapping is unambiguous. Earlier we mixed
    cell+multi_cell which produced a cursor that didn't have enough
    horizontal room left in the row, raising FPDFException.
    """
    pdf.set_font("Helvetica", size=10)
    _set_color(pdf, _INK)
    if not items:
        _set_color(pdf, _INK_SOFT)
        pdf.cell(0, 6, _safe(pdf, "- none -"), 0, 1)
        _set_color(pdf, _INK)
        return
    content_w = pdf.w - pdf.l_margin - pdf.r_margin
    for item in items[:max_items]:
        text = _safe(pdf, str(item))
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(content_w, 5, "  - " + text)


def _dim_card(
    pdf, name: str, dim: DimensionAssessment, *, x: float, y: float, w: float, h: float
) -> None:
    """Compact card showing one dimension's score + 1-line summary.

    We draw the card outline manually because fpdf2's cell helpers
    don't compose with multi-line text inside a fixed-height frame.
    """
    pdf.set_xy(x, y)
    _set_border(pdf, _BORDER)
    _set_fill(pdf, _CARD_BG)
    pdf.rect(x, y, w, h, "DF")

    score = int(dim.score_0_100 or 0)
    if score >= 70:
        accent = _POSITIVE
    elif score >= 50:
        accent = _ACCENT
    elif score >= 30:
        accent = _WATCH
    else:
        accent = _NEGATIVE

    pdf.set_xy(x + 3, y + 2)
    pdf.set_font("Helvetica", "B", 8)
    _set_color(pdf, _INK_SOFT)
    pdf.cell(w - 6, 4, _safe(pdf, name.upper()), 0, 1)

    pdf.set_xy(x + 3, y + 7)
    pdf.set_font("Helvetica", "B", 22)
    _set_color(pdf, accent)
    pdf.cell(w - 6, 9, str(score), 0, 1)

    pdf.set_xy(x + 3, y + 17)
    pdf.set_font("Helvetica", size=8)
    _set_color(pdf, _INK_SOFT)
    pdf.cell(w - 6, 3.5, _safe(pdf, "/ 100"), 0, 1)

    pdf.set_xy(x + 3, y + 22)
    pdf.set_font("Helvetica", size=8)
    _set_color(pdf, _INK)
    first_point = (dim.key_points[0] if dim.key_points else "Insufficient data.")[:120]
    pdf.multi_cell(w - 6, 4, _safe(pdf, first_point))
    _set_color(pdf, _INK)


# ── page composers ────────────────────────────────────────────────


def _page_cover(pdf, dossier: dict[str, Any], a: DeepAnalysis) -> None:
    pdf.add_page()
    # Title
    pdf.set_font("Helvetica", "B", 22)
    _set_color(pdf, _INK)
    title = f"{a.ticker} - Institutional Equity Research"
    pdf.cell(0, 12, _safe(pdf, title), 0, 1)

    pdf.set_font("Helvetica", size=10)
    _set_color(pdf, _INK_SOFT)
    profile = dossier.get("profile") or {}
    market = dossier.get("market") or {}
    company = profile.get("name") or a.ticker
    sector = profile.get("sector") or "—"
    industry = profile.get("industry") or "—"
    mcap = _fmt_money(market.get("market_cap"))
    price = _fmt_money(market.get("current_price"))
    pdf.cell(
        0,
        5,
        _safe(pdf, f"{company} - {sector} / {industry} - Market cap {mcap} - Last price {price}"),
        0,
        1,
    )
    pdf.ln(4)

    # Verdict ribbon
    rating = a.verdict.rating
    rating_color = _RATING_COLOR.get(rating, _ACCENT)
    conf_color = _CONF_COLOR.get(a.verdict.confidence, _INK_SOFT)
    pdf.set_font("Helvetica", "B", 12)
    _set_fill(pdf, rating_color)
    _set_color(pdf, (255, 255, 255))
    pdf.cell(45, 10, _safe(pdf, rating), border=0, ln=0, align="C", fill=True)
    pdf.set_font("Helvetica", size=10)
    _set_fill(pdf, _CARD_BG)
    _set_color(pdf, _INK)
    pdf.cell(
        145,
        10,
        _safe(
            pdf,
            f"  Confidence: {a.verdict.confidence.title()}  -  "
            f"Target sleeve: {a.verdict.target_weight_pct_band or 'n/a'}",
        ),
        border=0,
        ln=1,
        fill=True,
    )
    pdf.ln(2)

    # Thesis
    pdf.set_font("Helvetica", "B", 10)
    _set_color(pdf, _INK)
    pdf.cell(0, 6, _safe(pdf, "Thesis"), 0, 1)
    pdf.set_font("Helvetica", size=10)
    pdf.multi_cell(
        0,
        5,
        _safe(pdf, a.verdict.thesis_one_liner or "—"),
    )
    pdf.ln(2)

    # 5-card score grid
    _section_header(pdf, "Dimension Scorecard")
    available_w = pdf.w - pdf.l_margin - pdf.r_margin
    card_w = (available_w - 4 * 2) / 5  # 4 gaps between 5 cards
    card_h = 36
    y = pdf.get_y()
    for i, key in enumerate(("quality", "fundamentals", "growth", "technicals", "sentiment")):
        dim = a.dimensions.get(key)
        if dim is None:
            dim = DimensionAssessment(score_0_100=50, key_points=[], evidence=[])
        x = pdf.l_margin + i * (card_w + 2)
        _dim_card(pdf, key, dim, x=x, y=y, w=card_w, h=card_h)
    pdf.set_y(y + card_h + 4)

    # Radar chart of the same 5 scores — gives the PM a visual snapshot
    # that survives a printout. We render only if matplotlib is happy.
    radar_png = _render_radar_png(a)
    if radar_png:
        chart_w = 80  # mm
        chart_x = pdf.w - pdf.r_margin - chart_w
        chart_y = pdf.get_y()
        _embed_png(pdf, radar_png, x=chart_x, y=chart_y, w=chart_w)
        pdf.set_y(chart_y + 60)

    # Confidence + AI disclaimer
    pdf.set_font("Helvetica", "I", 8)
    _set_color(pdf, _INK_SOFT)
    pdf.multi_cell(
        0,
        4,
        _safe(
            pdf,
            "Confidence is computed from dossier completeness. Where data is "
            "missing the analyst defers and flags the gap in the Appendix. "
            "Educational only - not investment advice.",
        ),
    )


def _page_fund_val(pdf, dossier: dict[str, Any], a: DeepAnalysis) -> None:
    pdf.add_page()
    fund = dossier.get("fundamentals") or {}
    val = dossier.get("valuation") or {}

    _section_header(pdf, "Fundamentals")
    rows = [
        ("P/E (TTM)", _fmt_num(fund.get("pe_ttm"))),
        ("P/S (TTM)", _fmt_num(fund.get("ps_ttm"))),
        ("P/B", _fmt_num(fund.get("pb"))),
        ("EV / EBITDA", _fmt_num(fund.get("ev_ebitda"))),
        ("ROE", _fmt_pct(fund.get("roe"))),
        ("ROA", _fmt_pct(fund.get("roa"))),
        ("Gross Margin", _fmt_pct(fund.get("gross_margin"))),
        ("Operating Margin", _fmt_pct(fund.get("operating_margin"))),
        ("Net Margin", _fmt_pct(fund.get("net_margin"))),
        ("EPS (TTM)", _fmt_num(fund.get("eps_ttm"))),
        ("Dividend Yield", _fmt_pct(fund.get("dividend_yield"))),
        ("Debt / Equity", _fmt_num(fund.get("debt_to_equity"))),
        ("Current Ratio", _fmt_num(fund.get("current_ratio"))),
        ("Free Cash Flow", _fmt_money(fund.get("free_cash_flow"))),
        ("FCF Yield", _fmt_pct(fund.get("fcf_yield"))),
    ]
    _kv_table(pdf, rows)

    _section_header(pdf, "Valuation (DCF Anchor)")
    val_rows = [
        ("DCF Intrinsic Value", _fmt_money(val.get("dcf_intrinsic_value"))),
        ("DCF Upside vs. Spot", _fmt_pct(val.get("dcf_upside_pct"), signed=True)),
        ("WACC", _fmt_pct(val.get("wacc"))),
        ("Terminal Growth", _fmt_pct(val.get("terminal_growth"))),
    ]
    _kv_table(pdf, val_rows)

    _section_header(pdf, "Analyst Narrative - Fundamentals")
    dim = a.dimensions.get("fundamentals") or DimensionAssessment(score_0_100=50)
    _bullet_list(pdf, dim.key_points)
    pdf.ln(1)
    pdf.set_font("Helvetica", "I", 8)
    _set_color(pdf, _INK_SOFT)
    pdf.multi_cell(
        0,
        4,
        _safe(pdf, "Evidence: " + (" | ".join(dim.evidence) if dim.evidence else "—")),
    )
    _set_color(pdf, _INK)


def _page_growth_technicals(
    pdf,
    dossier: dict[str, Any],
    a: DeepAnalysis,
    *,
    price_history=None,
) -> None:
    pdf.add_page()
    fund = dossier.get("fundamentals") or {}
    tech = dossier.get("technicals") or {}

    _section_header(pdf, "Growth")
    growth_rows = [
        ("Revenue Growth Y/Y", _fmt_pct(fund.get("revenue_growth_yoy"), signed=True)),
        ("Earnings Growth Y/Y", _fmt_pct(fund.get("earnings_growth_yoy"), signed=True)),
    ]
    _kv_table(pdf, growth_rows)
    dim_g = a.dimensions.get("growth") or DimensionAssessment(score_0_100=50)
    _bullet_list(pdf, dim_g.key_points)

    _section_header(pdf, "Technicals & Quant Risk")
    # Render the 1y price chart when caller passed history. Sits above
    # the metrics table so the PM eyeballs the picture before the table.
    price_png = _render_price_chart_png(price_history)
    if price_png:
        chart_w = pdf.w - pdf.l_margin - pdf.r_margin
        _embed_png(pdf, price_png, x=pdf.l_margin, y=pdf.get_y(), w=chart_w)
        # Manually advance the cursor — pdf.image() doesn't auto-step.
        pdf.set_y(pdf.get_y() + 64)
        pdf.set_font("Helvetica", "I", 7)
        _set_color(pdf, _INK_SOFT)
        pdf.cell(0, 4, _safe(pdf, "1y close with SMA-50 and SMA-200 overlays."), 0, 1)
        _set_color(pdf, _INK)
        pdf.ln(1)

    tech_rows = [
        ("RSI(14)", _fmt_num(tech.get("rsi_14"))),
        ("SMA 50", _fmt_money(tech.get("sma_50"))),
        ("SMA 200", _fmt_money(tech.get("sma_200"))),
        ("MACD", _fmt_num(tech.get("macd"), places=4)),
        ("MACD Signal", _fmt_num(tech.get("macd_signal"), places=4)),
        ("52-Week High", _fmt_money(tech.get("fifty_two_week_high"))),
        ("52-Week Low", _fmt_money(tech.get("fifty_two_week_low"))),
        ("Max Drawdown (1y)", _fmt_pct(tech.get("max_drawdown_1y"), signed=True)),
        ("Beta", _fmt_num((dossier.get("market") or {}).get("beta"))),
        ("Implied Volatility", _fmt_pct((dossier.get("market") or {}).get("implied_volatility"))),
    ]
    _kv_table(pdf, tech_rows)
    dim_t = a.dimensions.get("technicals") or DimensionAssessment(score_0_100=50)
    _bullet_list(pdf, dim_t.key_points)

    _section_header(pdf, "Catalysts in next 90 days")
    _bullet_list(pdf, list(a.catalysts_90d), max_items=8)


def _page_sentiment_risks(pdf, dossier: dict[str, Any], a: DeepAnalysis) -> None:
    pdf.add_page()
    ratings = dossier.get("ratings") or {}
    ownership = dossier.get("ownership") or {}
    insider = dossier.get("insider") or {}

    _section_header(pdf, "Sentiment & Sell-Side")
    sent_rows = [
        ("Consensus Rating", _safe(pdf, ratings.get("analyst_rating") or "—")),
        ("Analyst Count", str(ratings.get("analyst_count") or "—")),
        (
            "Target (Consensus / High / Low)",
            (
                f"{_fmt_money((ratings.get('price_targets') or {}).get('consensus'))} / "
                f"{_fmt_money((ratings.get('price_targets') or {}).get('high'))} / "
                f"{_fmt_money((ratings.get('price_targets') or {}).get('low'))}"
            ),
        ),
    ]
    _kv_table(pdf, sent_rows)

    _section_header(pdf, "Insider Activity (6m)")
    ins_rows = [
        ("Net Shares Bought", str(insider.get("net_shares_6m") or "—")),
        ("Buy Transactions", str(insider.get("buy_count_6m") or "—")),
        ("Sell Transactions", str(insider.get("sell_count_6m") or "—")),
        ("Most Recent Transaction", _safe(pdf, insider.get("latest_transaction") or "—")),
    ]
    _kv_table(pdf, ins_rows)

    _section_header(pdf, "Institutional Ownership")
    pdf.set_font("Helvetica", size=9)
    inst_pct = ownership.get("institutional_pct")
    pdf.cell(
        0,
        5,
        _safe(
            pdf,
            (
                f"Institutional ownership: {_fmt_pct(inst_pct)}"
                if inst_pct is not None
                else "Institutional ownership: -"
            ),
        ),
        0,
        1,
    )
    top_inst = ownership.get("top_institutions") or []
    if top_inst:
        for item in top_inst[:5]:
            holder = (item.get("holder") if isinstance(item, dict) else str(item)) or "—"
            shares = item.get("shares") if isinstance(item, dict) else None
            pct = item.get("pct") if isinstance(item, dict) else None
            line = (
                f"- {holder}: {_fmt_pct(pct) if pct is not None else '-'} ({shares or '-'} shares)"
            )
            pdf.cell(0, 5, _safe(pdf, line), 0, 1)
    else:
        pdf.cell(0, 5, _safe(pdf, "- none -"), 0, 1)

    _section_header(pdf, "Risks the PM should track")
    _bullet_list(pdf, list(a.risks), max_items=8)


def _page_appendix(pdf, dossier: dict[str, Any], a: DeepAnalysis) -> None:
    pdf.add_page()
    _section_header(pdf, "What would change my mind in 90 days")
    _bullet_list(pdf, list(a.would_change_mind))

    _section_header(pdf, "Data gaps detected")
    gaps = list(a.data_gaps or [])
    _bullet_list(pdf, gaps or ["No material gaps - dossier complete."])

    _section_header(pdf, "Metadata")
    meta_rows = [
        ("Ticker", a.ticker),
        ("Generated", _safe(pdf, a.as_of or dossier.get("as_of") or "—")),
        ("Rating", _safe(pdf, a.verdict.rating)),
        ("Confidence", _safe(pdf, a.verdict.confidence)),
        ("Dossier completeness", _fmt_pct(_dossier_completeness(dossier))),
    ]
    _kv_table(pdf, meta_rows)

    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 8)
    _set_color(pdf, _INK_SOFT)
    pdf.multi_cell(
        0,
        4,
        _safe(
            pdf,
            "Disclaimer. This document is generated by MindMarket AI's "
            "automated analyst pipeline using public market data and an LLM. "
            "It is educational only and is not investment advice, an offer to "
            "buy or sell, or a recommendation to take any action. Past "
            "performance does not predict future results.",
        ),
    )


def _dossier_completeness(dossier: dict[str, Any]) -> float:
    """Heuristic 0..1 completeness score for the metadata page.

    Looks at the same fields ``data_gaps_detected`` covers, plus a few
    extras that matter for the PDF's tables. Pure math; no I/O."""
    total = 0
    present = 0
    for section, fields in (
        (
            "fundamentals",
            (
                "pe_ttm",
                "roe",
                "net_margin",
                "operating_margin",
                "revenue_growth_yoy",
                "free_cash_flow",
            ),
        ),
        ("technicals", ("rsi_14", "sma_50", "sma_200", "macd")),
        ("market", ("current_price", "market_cap", "beta")),
        ("valuation", ("dcf_intrinsic_value",)),
    ):
        for key in fields:
            total += 1
            if (dossier.get(section) or {}).get(key) is not None:
                present += 1
    return (present / total) if total else 0.0


# ── public entry point ─────────────────────────────────────────────


def build_equity_pdf(
    dossier: dict[str, Any],
    analysis: DeepAnalysis,
    *,
    price_history=None,
) -> bytes:
    """Compose the full institutional report and return PDF bytes.

    Parameters
    ----------
    dossier:
        Output of :func:`libs.analysis.equity_research.build_company_dossier`.
    analysis:
        A validated :class:`DeepAnalysis`.
    price_history:
        Optional pandas Series indexed by date with closing prices
        (1y window typical). When provided we embed a 1-year price
        chart on page 3 alongside the technicals table.

    The function NEVER raises on missing fields — every helper handles
    None and prints ``—``. It DOES raise if fpdf2 itself isn't
    importable; the UI catches that and shows a "install fpdf2"
    message.
    """
    pdf = _new_pdf()

    # Side-effect: also flips the default font + disables the latin-1
    # sanitiser when CJK is available. Stored on ``pdf`` so the page
    # composers can read it.
    pdf._mm_cjk_font = _register_cjk_font(pdf)  # type: ignore[attr-defined]
    if pdf._mm_cjk_font:  # type: ignore[attr-defined]
        # The footer subclass also needs to use the Unicode font;
        # otherwise the dash + page number stay Helvetica but the
        # title is CJK — looks inconsistent. Override here.
        pdf.set_font(pdf._mm_cjk_font, "", 10)

    _page_cover(pdf, dossier or {}, analysis)
    _page_fund_val(pdf, dossier or {}, analysis)
    _page_growth_technicals(pdf, dossier or {}, analysis, price_history=price_history)
    _page_sentiment_risks(pdf, dossier or {}, analysis)
    _page_appendix(pdf, dossier or {}, analysis)

    # fpdf2 returns ``bytearray`` from .output(dest='S') in v2; convert.
    raw = pdf.output(dest="S")
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw)
    # Older string-returning fallback.
    return bytes(str(raw), "latin-1", errors="replace")


def build_equity_pdf_to_buffer(
    dossier: dict[str, Any],
    analysis: DeepAnalysis,
    *,
    price_history=None,
) -> io.BytesIO:
    """Convenience wrapper for callers that want a file-like object
    (e.g. ``st.download_button`` accepts BytesIO directly)."""
    return io.BytesIO(build_equity_pdf(dossier, analysis, price_history=price_history))
