"""Tests for libs/analysis/equity_pdf.py — institutional report
builder. We don't pixel-diff the PDF; we just make sure the binary is
well-formed, complete, and survives all the missing-field corner cases
that bite production (NaN inputs, empty dossier, CJK strings, etc.)."""

from __future__ import annotations

from libs.analysis.equity_pdf import (
    _dossier_completeness,
    _fmt_money,
    _fmt_num,
    _fmt_pct,
    _sanitize_text,
    build_equity_pdf,
    build_equity_pdf_to_buffer,
)
from libs.analysis.equity_research import (
    DeepAnalysis,
    DimensionAssessment,
    Verdict,
    analyze_equity,
    build_company_dossier,
)


def _full_fetcher(t, k=""):
    return {
        "ticker": t,
        "company_name": "Fake Co.",
        "sector": "Technology",
        "industry": "Software",
        "description": "Software co.",
        "employees": 200,
        "market_cap": 2.5e9,
        "current_price": 50.0,
        "institutional_pct": 0.80,
        "fundamentals": {
            "P/E (TTM)": 22.4,
            "ROE": 0.283,
            "Net Margin": 0.21,
            "Rev Growth": 0.18,
            "Beta": 1.2,
            "FCF": 4.5e8,
        },
        "valuation": {"intrinsic_value": 60.0, "upside_pct": 0.20},
        "technicals": {
            "rsi": 55.3,
            "sma_50": 48.2,
            "sma_200": 44.1,
            "macd": 0.42,
            "macd_signal": 0.31,
        },
        "insider": {"net_shares_6m": -1500, "buy_count_6m": 1, "sell_count_6m": 3},
        "analyst_rating": "Buy",
        "analyst_count": 14,
        "price_targets": {"consensus": 58},
        "recent_upgrades": [],
        "top_institutions": [{"holder": "BlackRock", "pct": 0.11}],
        "summary_context": "ctx",
    }


def _empty_fetcher(t, k=""):
    return {"ticker": t}


def _full_analysis(ticker: str = "FAKE") -> DeepAnalysis:
    return DeepAnalysis(
        ticker=ticker,
        as_of="2026-05-26T12:00:00+00:00",
        verdict=Verdict(
            rating="BUY",
            confidence="high",
            target_weight_pct_band="2-4%",
            thesis_one_liner="Compounder at fair multiple.",
        ),
        dimensions={
            k: DimensionAssessment(
                score_0_100=70,
                key_points=[f"{k} point one", f"{k} point two"],
                evidence=[f"dossier.{k}.foo=bar"],
            )
            for k in ("quality", "fundamentals", "growth", "technicals", "sentiment")
        },
        catalysts_90d=["Earnings", "Conference"],
        risks=["Concentration"],
        data_gaps=[],
        would_change_mind=["Margins compress", "Insider sales accelerate", "Guide down"],
    )


# ── formatters ──────────────────────────────────────────────────────


def test_fmt_helpers_return_em_dash_on_none():
    assert _fmt_money(None) == "—"
    assert _fmt_pct(None) == "—"
    assert _fmt_num(None) == "—"


def test_fmt_helpers_handle_non_numeric():
    assert _fmt_money("not-a-number") == "—"
    assert _fmt_pct("abc") == "—"


def test_fmt_money_buckets():
    assert "B" in _fmt_money(2.5e9)
    assert "M" in _fmt_money(4.5e8)
    assert _fmt_money(123.4) == "$123.40"


def test_fmt_pct_signed():
    assert _fmt_pct(0.15, signed=True) == "+15.0%"
    assert _fmt_pct(-0.05, signed=True) == "-5.0%"


def test_sanitize_text_strips_non_latin1():
    """fpdf2 with default font is latin-1 only. CJK + emojis must be
    replaced rather than crash the PDF write."""
    out = _sanitize_text("营收增长 18% — strong 🎯")
    assert isinstance(out, str)
    # Replacement codepoint may end up as '?' or the original char
    # depending on Python — what matters is that encoding to latin-1
    # round-trips without raising.
    out.encode("latin-1")


def test_sanitize_text_replaces_typography():
    assert _sanitize_text("hello—world") == "hello-world"
    assert _sanitize_text("“quoted”") == '"quoted"'
    assert _sanitize_text("a → b") == "a -> b"


# ── completeness ────────────────────────────────────────────────────


def test_dossier_completeness_full():
    d = build_company_dossier("FAKE", fetcher=_full_fetcher)
    score = _dossier_completeness(d)
    assert 0.8 <= score <= 1.0


def test_dossier_completeness_empty():
    d = build_company_dossier("FAKE", fetcher=_empty_fetcher)
    score = _dossier_completeness(d)
    assert score == 0.0


# ── PDF build smoke ─────────────────────────────────────────────────


def test_build_equity_pdf_returns_valid_pdf_bytes():
    d = build_company_dossier("FAKE", fetcher=_full_fetcher)
    a = _full_analysis("FAKE")
    pdf_bytes = build_equity_pdf(d, a)
    assert isinstance(pdf_bytes, bytes)
    # PDF spec: first 5 bytes are %PDF- followed by the version.
    assert pdf_bytes[:5] == b"%PDF-"
    # %%EOF is the standard PDF trailer.
    assert b"%%EOF" in pdf_bytes[-256:]
    # Size sanity — at least 4 KB for a five-page report.
    assert len(pdf_bytes) > 4000


def test_build_equity_pdf_handles_empty_dossier():
    """Even with zero data, the PDF should still build (all values
    become em-dashes; the analyst placeholder kicks in)."""
    d = build_company_dossier("FAKE", fetcher=_empty_fetcher)
    a = analyze_equity(d, llm_callable=None)  # placeholder path
    pdf_bytes = build_equity_pdf(d, a)
    assert pdf_bytes[:5] == b"%PDF-"
    assert len(pdf_bytes) > 2000  # cover + appendix at minimum


def test_build_equity_pdf_with_chinese_thesis_does_not_crash():
    """Chinese text from a CN-language LLM must not blow up fpdf2."""
    d = build_company_dossier("FAKE", fetcher=_full_fetcher)
    a = _full_analysis("FAKE")
    # Inject CJK into a couple of human-readable fields.
    a = a.model_copy(
        update={
            "verdict": a.verdict.model_copy(
                update={"thesis_one_liner": "估值合理的护城河复利型公司"}
            ),
        }
    )
    a.risks.append("集中度风险")
    pdf_bytes = build_equity_pdf(d, a)
    assert pdf_bytes[:5] == b"%PDF-"


def test_build_equity_pdf_to_buffer_yields_seekable_stream():
    d = build_company_dossier("FAKE", fetcher=_full_fetcher)
    a = _full_analysis("FAKE")
    buf = build_equity_pdf_to_buffer(d, a)
    # Streamlit's download_button is happy with BytesIO; we just verify
    # it's seekable + holds the expected header.
    head = buf.read(5)
    assert head == b"%PDF-"
    buf.seek(0)
    assert buf.tell() == 0


# ── CJK font detection ─────────────────────────────────────────────


def test_resolve_cjk_font_returns_none_when_no_font_path_set(monkeypatch, tmp_path):
    """In a hermetic environment (CI, Lambda) no font file exists. The
    function MUST return None — never raise — so the PDF falls back to
    Helvetica + latin-1 sanitiser."""
    from libs.analysis import equity_pdf

    # Wipe the env override + temporarily point to an empty directory
    # so the relative paths in _CJK_FONT_SEARCH_PATHS can't match a
    # real repo-local font.
    monkeypatch.delenv("MINDMARKET_CJK_FONT_PATH", raising=False)
    monkeypatch.chdir(tmp_path)

    # Stub the search list to only the relative fonts/ entries — we
    # don't want this test to flake based on the developer's machine.
    monkeypatch.setattr(
        equity_pdf,
        "_CJK_FONT_SEARCH_PATHS",
        ("fonts/NotoSansSC-Regular.ttf",),
    )
    assert equity_pdf._resolve_cjk_font() is None


def test_resolve_cjk_font_honors_env_override(monkeypatch, tmp_path):
    from libs.analysis import equity_pdf

    fake_font = tmp_path / "fake.ttf"
    fake_font.write_bytes(b"\x00\x01\x00\x00")  # fake TTF magic
    monkeypatch.setenv("MINDMARKET_CJK_FONT_PATH", str(fake_font))
    assert equity_pdf._resolve_cjk_font() == str(fake_font)


def test_sanitize_text_unicode_safe_keeps_cjk():
    from libs.analysis.equity_pdf import _sanitize_text

    out = _sanitize_text("公司质地优秀", unicode_safe=True)
    assert out == "公司质地优秀"  # untouched in unicode mode


def test_sanitize_text_default_drops_cjk():
    from libs.analysis.equity_pdf import _sanitize_text

    out = _sanitize_text("公司")
    # Replacement may be '?', '\x1a', or another marker depending on
    # codec; what matters is the round-trip works and no CJK survives.
    assert "公" not in out
    out.encode("latin-1")  # MUST be safely encodable


# ── chart helpers ──────────────────────────────────────────────────


def test_render_radar_png_returns_png_bytes():
    from libs.analysis.equity_pdf import _render_radar_png

    a = _full_analysis("FAKE")
    png = _render_radar_png(a)
    # matplotlib may be unavailable in some test environments; the
    # helper returns None in that case. Assert the contract either way.
    if png is not None:
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        assert len(png) > 800  # at least a small chart, not a stub


def test_render_radar_png_handles_missing_dimensions():
    """Even if some dimensions are absent, the radar should fill 50
    placeholders rather than crash."""
    from libs.analysis.equity_pdf import _render_radar_png

    a = DeepAnalysis(
        ticker="X",
        verdict=Verdict(
            rating="HOLD",
            confidence="low",
            target_weight_pct_band="",
            thesis_one_liner="",
        ),
        dimensions={},
    )
    png = _render_radar_png(a)
    # None is acceptable (no matplotlib); otherwise must be valid PNG.
    if png is not None:
        assert png[:4] == b"\x89PNG"


def test_render_price_chart_skips_short_series():
    """Less than 30 points → return None so the PDF doesn't waste page
    real estate on a near-empty chart."""
    import pandas as pd

    from libs.analysis.equity_pdf import _render_price_chart_png

    ser = pd.Series([100.0, 101.0, 99.0])
    assert _render_price_chart_png(ser) is None


def test_render_price_chart_returns_png_for_full_series():
    import numpy as np
    import pandas as pd

    from libs.analysis.equity_pdf import _render_price_chart_png

    ser = pd.Series(
        100 + np.cumsum(np.random.default_rng(0).normal(0, 1, 252)),
        index=pd.date_range("2025-01-01", periods=252, freq="B"),
    )
    png = _render_price_chart_png(ser)
    if png is not None:
        assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_build_pdf_with_price_history_kwarg():
    """Smoke: passing price_history doesn't change the public contract
    (still bytes, still PDF) — just adds a chart on page 3."""
    import numpy as np
    import pandas as pd

    d = build_company_dossier("FAKE", fetcher=_full_fetcher)
    a = _full_analysis("FAKE")
    ser = pd.Series(
        100 + np.cumsum(np.random.default_rng(1).normal(0, 1, 252)),
        index=pd.date_range("2025-01-01", periods=252, freq="B"),
    )
    pdf_bytes = build_equity_pdf(d, a, price_history=ser)
    assert pdf_bytes[:5] == b"%PDF-"
    # With a chart embedded the file is meaningfully larger than the
    # text-only baseline (which is ~8 KB).
    assert len(pdf_bytes) > 20000


def test_build_pdf_to_buffer_accepts_price_history():
    import numpy as np
    import pandas as pd

    d = build_company_dossier("FAKE", fetcher=_full_fetcher)
    a = _full_analysis("FAKE")
    ser = pd.Series(
        np.linspace(100, 120, 252),
        index=pd.date_range("2025-01-01", periods=252, freq="B"),
    )
    buf = build_equity_pdf_to_buffer(d, a, price_history=ser)
    assert buf.read(5) == b"%PDF-"
