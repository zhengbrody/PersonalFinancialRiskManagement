"""Build self-contained shareable portfolio risk reports."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Any, Mapping, Sequence


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        result = float(value)
    except (TypeError, ValueError):
        return default
    if result != result or result in (float("inf"), float("-inf")):
        return default
    return result


def _money(value: Any) -> str:
    return f"${_num(value):,.0f}"


def _pct(value: Any) -> str:
    return f"{_num(value):.1%}"


def _multiple(value: Any) -> str:
    result = _num(value)
    if result <= 0:
        return "--"
    return f"{result:.2f}x"


def _metric(label: str, value: str, tone: str = "") -> str:
    tone_class = f" {escape(tone)}" if tone else ""
    return (
        f'<div class="metric{tone_class}">'
        f"<span>{escape(label)}</span>"
        f"<strong>{escape(value)}</strong>"
        "</div>"
    )


def _top_weights(weights: Mapping[str, Any], limit: int = 8) -> list[tuple[str, float]]:
    rows: list[tuple[str, float]] = []
    for ticker, weight in (weights or {}).items():
        value = _num(weight)
        if value > 0:
            rows.append((str(ticker).upper(), value))
    return sorted(rows, key=lambda item: item[1], reverse=True)[:limit]


def _action_title(card: Mapping[str, Any]) -> str:
    return str(card.get("title") or card.get("headline") or card.get("kicker") or "Review risk")


def _action_body(card: Mapping[str, Any]) -> str:
    return str(card.get("body") or card.get("description") or card.get("reason") or "")


def build_shareable_report_html(
    *,
    report: Any,
    weights: Mapping[str, Any] | None,
    meta: Mapping[str, Any] | None = None,
    action_cards: Sequence[Mapping[str, Any]] | None = None,
    generated_at: datetime | None = None,
    app_url: str = "https://mindmarket.app",
) -> str:
    """Return a portable HTML risk snapshot with escaped user-controlled values."""

    meta = meta or {}
    weights = weights or {}
    action_cards = action_cards or []
    generated_at = generated_at or datetime.now(timezone.utc)
    generated_label = generated_at.strftime("%Y-%m-%d %H:%M UTC")

    var_95 = getattr(report, "var_95", 0.0)
    cvar_95 = getattr(report, "cvar_95", 0.0)
    stress_loss = getattr(report, "stress_loss", 0.0)
    max_drawdown = getattr(report, "max_drawdown", 0.0)
    annual_vol = getattr(report, "annual_volatility", 0.0)
    sharpe = getattr(report, "sharpe_ratio", 0.0)

    metrics = "\n".join(
        [
            _metric("Net equity", _money(meta.get("net_equity"))),
            _metric("Total long", _money(meta.get("total_long"))),
            _metric("Cash balance", _money(meta.get("cash_balance"))),
            _metric("Margin loan", _money(meta.get("margin_loan")), "warn"),
            _metric("Contributed capital", _money(meta.get("contributed_capital"))),
            _metric("Leverage", _multiple(meta.get("leverage")), "warn"),
            _metric("VaR 95", _pct(var_95), "risk"),
            _metric("CVaR 95", _pct(cvar_95), "risk"),
            _metric("Stress loss", _pct(stress_loss), "risk"),
            _metric("Max drawdown", _pct(max_drawdown), "risk"),
            _metric("Annual volatility", _pct(annual_vol)),
            _metric("Sharpe ratio", f"{_num(sharpe):.2f}"),
        ]
    )

    top_rows = "\n".join(
        f"<tr><td>{escape(ticker)}</td><td>{_pct(weight)}</td></tr>"
        for ticker, weight in _top_weights(weights)
    )
    if not top_rows:
        top_rows = '<tr><td colspan="2">No holdings were included in this export.</td></tr>'

    action_rows = "\n".join(
        "<li>"
        f"<strong>{escape(_action_title(card))}</strong>"
        + (f"<p>{escape(_action_body(card))}</p>" if _action_body(card) else "")
        + "</li>"
        for card in action_cards[:5]
    )
    if not action_rows:
        action_rows = (
            "<li><strong>Run a fresh analysis in MindMarket AI for action cards.</strong></li>"
        )

    escaped_url = escape(app_url.rstrip("/") + "/")

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex, nofollow">
  <title>MindMarket AI Portfolio Risk Snapshot</title>
  <style>
    body {{ margin:0; background:#0b0e11; color:#e2e8f0; font-family:Inter,Arial,sans-serif; line-height:1.55; }}
    main {{ max-width:1040px; margin:0 auto; padding:48px 22px 72px; }}
    h1 {{ font-size:38px; line-height:1.12; margin:0 0 10px; color:#f8fafc; }}
    h2 {{ margin-top:34px; color:#f8fafc; }}
    p, li, td, th {{ color:#aab4c2; }}
    a {{ color:#39a3b5; }}
    .eyebrow {{ color:#39a3b5; font-size:12px; font-weight:700; letter-spacing:.16em; text-transform:uppercase; }}
    .hero {{ border:1px solid #1f2937; border-radius:10px; padding:26px; background:#111827; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:14px; margin-top:22px; }}
    .metric {{ border:1px solid #1f2937; border-radius:8px; padding:14px; background:#0f1319; }}
    .metric span {{ display:block; color:#8b949e; font-size:12px; margin-bottom:6px; }}
    .metric strong {{ font-size:22px; color:#f8fafc; }}
    .metric.risk strong {{ color:#f87171; }}
    .metric.warn strong {{ color:#fbbf24; }}
    table {{ width:100%; border-collapse:collapse; margin-top:12px; }}
    th, td {{ padding:12px; border-bottom:1px solid #1f2937; text-align:left; }}
    .panel {{ border:1px solid #1f2937; border-radius:8px; padding:18px; background:#0f1319; }}
    .disclaimer {{ margin-top:34px; padding-top:18px; border-top:1px solid #1f2937; color:#8b949e; font-size:13px; }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <div class="eyebrow">MindMarket AI</div>
      <h1>Portfolio Risk Snapshot</h1>
      <p>Generated {escape(generated_label)}. This export is a portable research snapshot, not investment advice.</p>
      <p><a href="{escaped_url}">Open MindMarket AI</a> to refresh data, update holdings, or run AI chat against the latest portfolio state.</p>
    </section>

    <section class="grid" aria-label="Portfolio risk metrics">
      {metrics}
    </section>

    <section class="panel">
      <h2>Top positions by weight</h2>
      <table>
        <thead><tr><th>Ticker</th><th>Weight</th></tr></thead>
        <tbody>{top_rows}</tbody>
      </table>
    </section>

    <section class="panel">
      <h2>What to look at first</h2>
      <ul>{action_rows}</ul>
    </section>

    <p class="disclaimer">
      Educational and research use only. MindMarket AI does not provide financial,
      investment, legal, or tax advice. AI-generated analysis and market data can
      be incomplete, stale, or incorrect. Verify all figures before making decisions.
    </p>
  </main>
</body>
</html>
"""
