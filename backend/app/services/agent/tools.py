"""The research agent's tool registry.

Every tool is a deterministic call into an existing risk service. The model
chooses which tools to call and with what arguments; it never produces a
financial number itself.

Boundaries, enforced here rather than in a prompt:

* **Closed registry.** A name not in ``REGISTRY`` cannot be executed.
* **Validated input.** Arguments are parsed by a pydantic model with bounds
  and ``extra="forbid"``; a bad call is returned to the model as an error.
* **No identity in arguments.** No tool accepts a user or portfolio id. The
  portfolio comes from ``ToolContext``, which the API builds from the caller's
  verified token — the model cannot point a tool at someone else's book.
* **Read-only.** No tool writes holdings, places an order, or saves anything.
* **Results are data.** A result is a structured packet (numbers, evidence,
  provenance); the runner tells the model to treat tool output as data.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Mapping, Optional

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from libs.mindmarket_core import factor_stress as fs

from .. import crisis_replay as replay_svc
from .. import factor_stress as stress_svc

_log = logging.getLogger(__name__)

MAX_CHANGES = 8


# ── context ───────────────────────────────────────────────────────────


@dataclass
class ToolContext:
    """What a tool may see. Built server-side from the authenticated caller."""

    holdings: Mapping[str, Mapping[str, Any]]
    cash_balance: float = 0.0
    margin_loan: float = 0.0
    option_specs_fn: Optional[Callable[[Mapping], list]] = None
    # Injectable seams; ``None`` means the real service, looked up at call time.
    stress_fn: Optional[Callable[..., dict]] = None
    replay_fn: Optional[Callable[..., dict]] = None
    _cache: dict[str, Any] = field(default_factory=dict)

    def stress(
        self,
        *,
        custom_shocks: Optional[dict[str, float]] = None,
        fill_unspecified: bool = True,
        holdings: Optional[Mapping[str, Mapping[str, Any]]] = None,
    ) -> dict:
        key = repr(
            (
                sorted((custom_shocks or {}).items()),
                fill_unspecified,
                (
                    None
                    if holdings is None
                    else sorted((k, v.get("shares")) for k, v in holdings.items())
                ),
            )
        )
        if key not in self._cache:
            self._cache[key] = self.run_stress(
                holdings=holdings if holdings is not None else self.holdings,
                cash_balance=self.cash_balance,
                margin_loan=self.margin_loan,
                custom_shocks=custom_shocks,
                fill_unspecified=fill_unspecified,
                option_specs_fn=self.option_specs_fn,
            )
        return self._cache[key]

    def run_stress(self, **kwargs: Any) -> dict:
        return (self.stress_fn or stress_svc.run_factor_stress)(**kwargs)

    def replay(self) -> dict:
        if "replay" not in self._cache:
            fn = self.replay_fn or replay_svc.run_crisis_replay
            self._cache["replay"] = fn(holdings=self.holdings)
        return self._cache["replay"]


# ── result packet ─────────────────────────────────────────────────────


class Evidence(BaseModel):
    """One citable figure. ``value`` is the display string the model may quote."""

    label: str
    value: str


class Provenance(BaseModel):
    source: str
    method: str
    as_of: Optional[str] = None
    assumptions: list[str] = []
    warnings: list[str] = []


class ToolResult(BaseModel):
    ok: bool = True
    summary: str  # one or two sentences for the model
    evidence: list[Evidence] = []
    provenance: Optional[Provenance] = None
    chart: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class ToolError(Exception):
    """A tool could not run for a reason the user should hear."""


def _pct(v: Optional[float], d: int = 1) -> str:
    return "n/a" if v is None else f"{v * 100:+.{d}f}%"


def _upct(v: Optional[float], d: int = 1) -> str:
    return "n/a" if v is None else f"{v * 100:.{d}f}%"


def _usd(v: Optional[float]) -> str:
    if v is None:
        return "n/a"
    return f"{'-' if v < 0 else ''}${abs(v):,.0f}"


def _shock_text(factor: str, shock: float) -> str:
    if factor == "vol":
        return f"VIX x{np.exp(shock):.2f}"
    if factor == "rates":
        return f"{-shock / fs.IEF_DURATION * 10_000:+.0f}bp"
    return _pct(shock)


_FACTOR_NAME = {f.id: f.label for f in fs.FACTORS}
_STRESS_SOURCE = "MindMarket seven-factor stress engine; adjusted daily closes (Yahoo Finance)"


def _stress_provenance(out: dict, extra: Optional[list[str]] = None) -> Provenance:
    c = out["coverage"]
    warnings = list(out.get("warnings") or [])
    if c["proxied"]:
        warnings.append(f"Sector stand-in loadings used for {', '.join(c['proxied'])}.")
    for u in c["unmodelled"]:
        warnings.append(
            f"{u['ticker']} ({_upct(u['weight'], 0)} of the stock book) could not be modelled "
            "and is left out."
        )
    for leg in c["option_legs_skipped"]:
        warnings.append(f"Option {leg['contract']} not repriced: {leg['reason']}.")
    return Provenance(
        source=_STRESS_SOURCE,
        method=f"{out['model_version']}: weekly OLS loadings, compounded moves, "
        "Black-Scholes option repricing",
        as_of=out["as_of"],
        assumptions=(extra or []) + out["assumptions"][:3],
        warnings=warnings,
    )


def _scenario_packet(out: dict, s: dict, extra: Optional[list[str]] = None) -> ToolResult:
    by_factor = sorted(s["by_factor"], key=lambda f: f["pnl_usd"])
    worst = [h for h in s["by_holding"] if h["pnl_usd"] < 0][:3]
    ev = [
        Evidence(label="Estimated change in net equity", value=_pct(s["pnl_pct"])),
        Evidence(label="Estimated P&L", value=_usd(s["pnl_usd"])),
        Evidence(
            label=f"{int(out['confidence'] * 100)}% range",
            value=f"{_usd(s['band_low_usd'])} to {_usd(s['band_high_usd'])}",
        ),
    ]
    for f in by_factor:
        if abs(f["pnl_usd"]) >= 1.0:
            ev.append(Evidence(label=f"From {_FACTOR_NAME[f['factor']]}", value=_usd(f["pnl_usd"])))
    for h in worst:
        ev.append(
            Evidence(
                label=f"{h['ticker']} move / P&L",
                value=f"{_pct(h['move_pct'])} / {_usd(h['pnl_usd'])}",
            )
        )
    opt = s["options"]
    if out["coverage"]["option_legs_repriced"]:
        ev.append(
            Evidence(
                label="Options, full reprice",
                value=f"{_usd(opt['pnl_usd'])} (delta {_usd(opt['delta_usd'])}, convexity "
                f"{_usd(opt['convexity_usd'])}, volatility {_usd(opt['vega_usd'])})",
            )
        )
    m = s["margin"]
    if out["account"]["margin_loan"] > 0:
        ev.append(
            Evidence(label="Margin used after the shock", value=_upct(m["utilisation_after"], 0))
        )
        if m["breach"]:
            ev.append(Evidence(label="Margin call", value="reached in this scenario"))
        elif m["breach_multiple"] is not None:
            ev.append(
                Evidence(
                    label="Margin call reached at", value=f"{m['breach_multiple']:.1f}x this shock"
                )
            )
    for f in fs.FACTOR_IDS:
        if abs(s["shocks"][f]) > 1e-9:
            tag = "you set" if f in s["specified"] else "implied by crisis correlations"
            ev.append(
                Evidence(
                    label=f"{_FACTOR_NAME[f]} move ({tag})", value=_shock_text(f, s["shocks"][f])
                )
            )
    lead = by_factor[0]
    summary = (
        f"{s['label']}: net equity {_pct(s['pnl_pct'])} ({_usd(s['pnl_usd'])}). "
        f"Largest driver: {_FACTOR_NAME[lead['factor']]} ({_usd(lead['pnl_usd'])})."
    )
    rows = [
        {"label": _FACTOR_NAME[f["factor"]], "value": f["pnl_usd"]}
        for f in s["by_factor"]
        if abs(f["pnl_usd"]) >= 1.0
    ]
    if out["coverage"]["option_legs_repriced"]:
        rows.append({"label": "Options", "value": opt["pnl_usd"]})
    return ToolResult(
        summary=summary,
        evidence=ev,
        provenance=_stress_provenance(out, extra),
        chart={
            "kind": "waterfall",
            "title": f"{s['label']}: P&L by factor",
            "unit": "usd",
            "rows": rows,
            "total": s["pnl_usd"],
        },
    )


# ── tool inputs ───────────────────────────────────────────────────────


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoInput(_Strict):
    pass


class StressInput(_Strict):
    """A user-defined shock. Give only the factors the user mentioned."""

    equity_pct: Optional[float] = Field(None, ge=-90, le=90, description="S&P 500 move, percent")
    nasdaq_pct: Optional[float] = Field(
        None, ge=-90, le=90, description="Nasdaq 100 move, percent. Use instead of equity_pct."
    )
    rates_bp: Optional[float] = Field(
        None, ge=-500, le=500, description="Treasury yield change, bp"
    )
    credit_pct: Optional[float] = Field(
        None, ge=-90, le=90, description="High-yield return versus Treasuries, percent"
    )
    usd_pct: Optional[float] = Field(None, ge=-50, le=50, description="Dollar move, percent")
    oil_pct: Optional[float] = Field(None, ge=-90, le=300, description="Oil move, percent")
    vix_multiple: Optional[float] = Field(
        None, gt=0.1, le=10, description="VIX multiple: 2 means volatility doubles"
    )
    gold_pct: Optional[float] = Field(None, ge=-90, le=90, description="Gold move, percent")
    hold_other_factors_flat: bool = Field(
        False, description="True to leave unmentioned factors unchanged"
    )


ScenarioId = Literal[
    "equity_crash",
    "rates_up_200bp",
    "credit_blowout",
    "usd_spike",
    "oil_spike",
    "vol_spike",
    "stagflation",
    "gfc_2008",
    "downgrade_2011",
    "cny_2015",
    "q4_2018",
    "covid_2020",
    "bear_2022",
    "svb_2023",
]
EpisodeId = Literal[
    "gfc_2008", "downgrade_2011", "cny_2015", "q4_2018", "covid_2020", "bear_2022", "svb_2023"
]


class NamedScenarioInput(_Strict):
    scenario_id: ScenarioId


class ReplayInput(_Strict):
    episode_id: Optional[EpisodeId] = Field(None, description="Omit for all episodes")


class DistributionInput(_Strict):
    regime: Literal["crisis", "calm"] = "crisis"


class PositionChange(_Strict):
    ticker: str = Field(..., min_length=1, max_length=12, pattern=r"^[A-Za-z0-9.\-]+$")
    change_pct: float = Field(
        ..., ge=-100, le=300, description="-50 halves the position, -100 removes it, +100 doubles"
    )


class CompareInput(_Strict):
    """A what-if the USER described. Never invent the changes yourself."""

    changes: list[PositionChange] = Field(..., min_length=1, max_length=MAX_CHANGES)
    scenario_id: ScenarioId = "equity_crash"


# ── handlers ──────────────────────────────────────────────────────────


def _overview(ctx: ToolContext, _: NoInput) -> ToolResult:
    out = ctx.stress()
    a, c = out["account"], out["concentration"]
    top = out["exposures"][:5]
    ev = [
        Evidence(label="Net equity", value=_usd(a["net_equity"])),
        Evidence(label="Long market value", value=_usd(a["gross_long"])),
        Evidence(label="Margin loan", value=_usd(a["margin_loan"])),
        Evidence(
            label="Leverage", value="n/a" if a["leverage"] is None else f"{a['leverage']:.2f}x"
        ),
        Evidence(label="Largest position weight", value=_upct(c["top_weight"])),
        Evidence(
            label="Effective number of holdings",
            value="n/a" if c["effective_holdings"] is None else f"{c['effective_holdings']:.1f}",
        ),
        Evidence(
            label="Share of the stock book modelled",
            value=_upct(out["coverage"]["modelled_weight"], 0),
        ),
    ]
    for e in top:
        ev.append(Evidence(label=f"{e['ticker']} weight", value=_upct(e["weight"])))
    lev = "no margin loan" if a["margin_loan"] <= 0 else f"leverage {a['leverage']:.2f}x"
    return ToolResult(
        summary=(
            f"Net equity {_usd(a['net_equity'])}, {lev}; largest position "
            f"{top[0]['ticker']} at {_upct(top[0]['weight'])}."
            if top
            else "No modelled holdings."
        ),
        evidence=ev,
        provenance=_stress_provenance(out),
        chart={
            "kind": "bars",
            "title": "Largest positions",
            "unit": "pct",
            "rows": [{"label": e["ticker"], "value": e["weight"]} for e in top],
        },
    )


def _exposure(ctx: ToolContext, _: NoInput) -> ToolResult:
    out = ctx.stress()
    d = out["decomposition"]["crisis"]
    ev = []
    for f in out["factors"]:
        if f["available"]:
            ev.append(
                Evidence(
                    label=f"Portfolio loading on {f['label']}",
                    value=f"{f['portfolio_loading']:.2f}",
                )
            )
    for f, share in sorted(d["factor_share"].items(), key=lambda kv: -abs(kv[1]))[:4]:
        ev.append(
            Evidence(
                label=f"Share of crisis volatility from {_FACTOR_NAME[f]}", value=_pct(share, 0)
            )
        )
    ev.append(
        Evidence(
            label="Share of crisis volatility from single-name risk", value=_pct(d["idio_share"], 0)
        )
    )
    for e in sorted(out["exposures"], key=lambda r: -abs(r["betas"]["equity"]) * r["weight"])[:3]:
        ev.append(Evidence(label=f"{e['ticker']} equity beta", value=f"{e['betas']['equity']:.2f}"))
    lead = max(d["factor_share"].items(), key=lambda kv: abs(kv[1]))
    return ToolResult(
        summary=f"{_FACTOR_NAME[lead[0]]} explains {_pct(lead[1], 0)} of the stock book's "
        f"crisis volatility; single-name risk {_pct(d['idio_share'], 0)}.",
        evidence=ev,
        provenance=_stress_provenance(out),
        chart={
            "kind": "bars",
            "title": "Share of crisis volatility by source",
            "unit": "pct",
            "rows": [{"label": _FACTOR_NAME[f], "value": v} for f, v in d["factor_share"].items()]
            + [{"label": "Single-name", "value": d["idio_share"]}],
        },
    )


def _translate(ctx: ToolContext, args: StressInput) -> tuple[dict[str, float], list[str]]:
    """User units → engine units. A Nasdaq move is converted to the S&P move
    that makes the model's QQQ move equal it, given the other shocks."""
    shocks: dict[str, float] = {}
    notes: list[str] = []
    if args.rates_bp is not None:
        shocks["rates"] = fs.rates_shock_from_bp(args.rates_bp)
    if args.credit_pct is not None:
        shocks["credit"] = args.credit_pct / 100
    if args.usd_pct is not None:
        shocks["usd"] = args.usd_pct / 100
    if args.oil_pct is not None:
        shocks["oil"] = args.oil_pct / 100
    if args.vix_multiple is not None:
        shocks["vol"] = float(np.log(args.vix_multiple))
    if args.gold_pct is not None:
        shocks["gold"] = args.gold_pct / 100
    if args.equity_pct is not None:
        shocks["equity"] = args.equity_pct / 100
    elif args.nasdaq_pct is not None:
        beta = _qqq_beta(ctx)
        target = np.log1p(args.nasdaq_pct / 100)
        if beta is None or abs(beta[0]) < 0.2:
            shocks["equity"] = args.nasdaq_pct / 100
            notes.append(
                "Nasdaq loadings were unavailable, so the Nasdaq move was applied to the S&P 500 as is."
            )
        else:
            other = np.array([shocks.get(f, 0.0) for f in fs.FACTOR_IDS])
            other[0] = 0.0
            log_eq = (target - float(beta @ fs.log_shock(other))) / float(beta[0])
            shocks["equity"] = float(np.clip(np.expm1(log_eq), -0.9, 0.9))
            notes.append(
                f"Nasdaq 100 {args.nasdaq_pct:+.0f}% was translated to S&P 500 "
                f"{shocks['equity'] * 100:+.1f}% using the Nasdaq fund's own factor loadings."
            )
    if not shocks:
        raise ToolError("No shock was given. Say how far at least one factor moves.")
    return shocks, notes


def _qqq_beta(ctx: ToolContext) -> Optional[np.ndarray]:
    if "qqq_beta" not in ctx._cache:
        beta = None
        try:
            out = ctx.run_stress(holdings={"QQQ": {"shares": 1.0, "asset_type": "etf"}})
            row = next(e for e in out["exposures"] if e["ticker"] == "QQQ")
            beta = np.array([row["betas"][f] for f in fs.FACTOR_IDS])
        except Exception as exc:  # noqa: BLE001 - fall back to treating Nasdaq as the S&P
            _log.warning("agent.qqq_beta_failed err=%s", type(exc).__name__)
        ctx._cache["qqq_beta"] = beta
    return ctx._cache["qqq_beta"]


def _stress(ctx: ToolContext, args: StressInput) -> ToolResult:
    shocks, notes = _translate(ctx, args)
    out = ctx.stress(custom_shocks=shocks, fill_unspecified=not args.hold_other_factors_flat)
    s = out["scenarios"][-1]
    if s["kind"] != "custom":
        raise ToolError("The custom scenario could not be run.")
    s = {**s, "label": "Your scenario"}
    if args.hold_other_factors_flat:
        notes.append("Factors you did not mention were held flat.")
    else:
        notes.append("Factors you did not mention move as they did alongside these in past crises.")
    return _scenario_packet(out, s, notes)


def _named(ctx: ToolContext, args: NamedScenarioInput) -> ToolResult:
    out = ctx.stress()
    s = next((x for x in out["scenarios"] if x["id"] == args.scenario_id), None)
    if s is None:
        raise ToolError("That scenario has no data for this portfolio.")
    packet = _scenario_packet(out, s, [s["source"]])
    if s.get("realised"):
        r = s["realised"]
        packet.evidence.append(
            Evidence(
                label="Holdings that existed then actually returned",
                value=f"{_pct(r['return_pct'])} (model for the same holdings: {_pct(r['model_return_pct'])})",
            )
        )
    return packet


def _scenarios(ctx: ToolContext, _: NoInput) -> ToolResult:
    out = ctx.stress()
    rows = sorted(out["scenarios"], key=lambda s: s["pnl_pct"])
    ev = [Evidence(label=f"{s['label']} ({s['id']})", value=_pct(s["pnl_pct"])) for s in rows]
    worst = rows[0]
    return ToolResult(
        summary=f"Worst of {len(rows)} scenarios: {worst['label']} at {_pct(worst['pnl_pct'])} of net equity.",
        evidence=ev,
        provenance=_stress_provenance(out),
        chart={
            "kind": "bars",
            "title": "Change in net equity by scenario",
            "unit": "pct",
            "rows": [{"label": s["label"], "value": s["pnl_pct"]} for s in rows],
        },
    )


def _replay(ctx: ToolContext, args: ReplayInput) -> ToolResult:
    out = ctx.replay()
    eps = out["episodes"]
    prov = Provenance(
        source=out["data_source"],
        method="Buy-and-hold replay of today's weights; holdings without prices in the "
        "episode are reconstructed from factor loadings and labelled",
        as_of=out["as_of"],
        assumptions=out["method"][:3],
        warnings=list(out["warnings"]),
    )
    if args.episode_id is None:
        ev = []
        for e in eps:
            ev.append(
                Evidence(
                    label=f"{e['label']} ({e['id']})",
                    value=f"book {_pct(e['portfolio']['return_pct'])}, S&P 500 "
                    f"{_pct(e['benchmark']['return_pct'])}, {_upct(e['coverage']['observed_weight'], 0)} observed",
                )
            )
        worst = min(eps, key=lambda e: e["portfolio"]["return_pct"])
        return ToolResult(
            summary=f"Worst replay: {worst['label']} at {_pct(worst['portfolio']['return_pct'])} "
            f"(S&P 500 {_pct(worst['benchmark']['return_pct'])}).",
            evidence=ev,
            provenance=prov,
            chart={
                "kind": "bars",
                "title": "Replayed return by episode",
                "unit": "pct",
                "rows": [{"label": e["label"], "value": e["portfolio"]["return_pct"]} for e in eps],
            },
        )
    e = next((x for x in eps if x["id"] == args.episode_id), None)
    if e is None:
        raise ToolError("That episode could not be replayed for this portfolio.")
    c, p = e["coverage"], e["portfolio"]
    ev = [
        Evidence(label="Replayed return", value=_pct(p["return_pct"])),
        Evidence(label="S&P 500 over the same days", value=_pct(e["benchmark"]["return_pct"])),
        Evidence(label="Worst drawdown", value=_pct(p["max_drawdown"])),
        Evidence(
            label="Observed from the holdings' own prices", value=_upct(c["observed_weight"], 0)
        ),
        Evidence(
            label="Reconstructed from factor loadings", value=_upct(c["reconstructed_weight"], 0)
        ),
        Evidence(label="No data, left out", value=_upct(c["unavailable_weight"], 0)),
    ]
    if p.get("worst_day"):
        ev.append(
            Evidence(
                label=f"Worst day ({p['worst_day']['date']})",
                value=_pct(p["worst_day"]["return_pct"]),
            )
        )
    for h in sorted(
        (h for h in e["holdings"] if h["contribution_pct"] is not None),
        key=lambda h: h["contribution_pct"],
    )[:3]:
        ev.append(
            Evidence(
                label=f"{h['ticker']} contribution ({h['kind']})", value=_pct(h["contribution_pct"])
            )
        )
    recon = [h["ticker"] for h in e["holdings"] if h["kind"] == "reconstructed"]
    if recon:
        prov.warnings.append(f"Reconstructed, not observed: {', '.join(recon)}.")
    return ToolResult(
        summary=f"{e['label']}: book {_pct(p['return_pct'])} against S&P 500 "
        f"{_pct(e['benchmark']['return_pct'])}; {_upct(c['observed_weight'], 0)} of the book is observed prices.",
        evidence=ev,
        provenance=prov,
        chart={
            "kind": "path",
            "title": f"{e['label']}: your book and the S&P 500",
            "rows": [
                {
                    "date": pt["date"],
                    "portfolio": pt["portfolio"] - 1.0,
                    "benchmark": pt["benchmark"] - 1.0,
                }
                for pt in e["path"]
            ],
        },
    )


def _distribution(ctx: ToolContext, args: DistributionInput) -> ToolResult:
    out = ctx.stress()
    d = out["distribution"][args.regime]
    ev = []
    for t in d["tails"]:
        lvl = int(t["level"] * 100)
        ev.append(
            Evidence(label=f"{lvl}% VaR, {out['horizon_weeks']} weeks", value=_upct(t["var"]))
        )
        ev.append(
            Evidence(label=f"{lvl}% CVaR, {out['horizon_weeks']} weeks", value=_upct(t["cvar"]))
        )
    if d["prob_margin_call"] is not None:
        ev.append(
            Evidence(
                label="Simulated chance of a margin call", value=_upct(d["prob_margin_call"], 2)
            )
        )
    t95 = d["tails"][0]
    return ToolResult(
        summary=f"In {args.regime} conditions, the {out['horizon_weeks']}-week 95% VaR is "
        f"{_upct(t95['var'])} of net equity and the average loss beyond it {_upct(t95['cvar'])}.",
        evidence=ev,
        provenance=_stress_provenance(
            out,
            [
                f"{d['n_sims']:,} simulated outcomes with fat tails; {args.regime}-period factor behaviour."
            ],
        ),
        chart={
            "kind": "histogram",
            "title": f"Simulated {out['horizon_weeks']}-week outcomes ({args.regime})",
            "rows": d["histogram"],
            "var95": -t95["var"],
        },
    )


def _compare(ctx: ToolContext, args: CompareInput) -> ToolResult:
    base = ctx.stress()
    held = {str(k).upper(): k for k in ctx.holdings}
    changed = {k: dict(v) for k, v in ctx.holdings.items()}
    notes = []
    for ch in args.changes:
        key = held.get(ch.ticker.upper())
        if key is None or stress_svc._is_option(ctx.holdings[key]):
            raise ToolError(f"{ch.ticker.upper()} is not a stock or fund in this portfolio.")
        shares = float(ctx.holdings[key].get("shares") or 0.0) * (1.0 + ch.change_pct / 100.0)
        changed[key]["shares"] = max(shares, 0.0)
        notes.append(f"{ch.ticker.upper()} position {ch.change_pct:+.0f}%")
    if not any(
        (v.get("shares") or 0) > 0 for v in changed.values() if not stress_svc._is_option(v)
    ):
        raise ToolError("That change would leave no stock holdings to analyse.")
    alt = ctx.stress(holdings=changed)

    def pick(out: dict) -> dict:
        return next(x for x in out["scenarios"] if x["id"] == args.scenario_id)

    b, a = pick(base), pick(alt)
    bt, at = base["distribution"]["crisis"]["tails"][0], alt["distribution"]["crisis"]["tails"][0]
    ev = [
        Evidence(label=f"{b['label']}: current book", value=_pct(b["pnl_pct"])),
        Evidence(label=f"{b['label']}: after the change", value=_pct(a["pnl_pct"])),
        Evidence(label="Crisis 95% VaR: current book", value=_upct(bt["var"])),
        Evidence(label="Crisis 95% VaR: after the change", value=_upct(at["var"])),
        Evidence(
            label="Largest position: current", value=_upct(base["concentration"]["top_weight"])
        ),
        Evidence(
            label="Largest position: after the change",
            value=_upct(alt["concentration"]["top_weight"]),
        ),
        Evidence(label="Net equity: current", value=_usd(base["account"]["net_equity"])),
        Evidence(label="Net equity: after the change", value=_usd(alt["account"]["net_equity"])),
    ]
    return ToolResult(
        summary=f"Hypothetical ({'; '.join(notes)}): {b['label']} goes from {_pct(b['pnl_pct'])} "
        f"to {_pct(a['pnl_pct'])} of net equity.",
        evidence=ev,
        provenance=_stress_provenance(
            alt,
            [
                "Hypothetical comparison of a change the user described. Nothing is saved or traded.",
                "Shares removed are treated as gone, not as cash added: net equity is lower by their value.",
            ],
        ),
        chart={
            "kind": "compare",
            "title": "Current book against the change",
            "unit": "pct",
            "rows": [
                {"label": b["label"], "current": b["pnl_pct"], "changed": a["pnl_pct"]},
                {"label": "Crisis 95% VaR", "current": -bt["var"], "changed": -at["var"]},
            ],
        },
    )


def _market(ctx: ToolContext, _: NoInput) -> ToolResult:
    from .. import market_regime, ml_regime
    from .._common import snapshot_to_mapping

    snap = snapshot_to_mapping(market_regime.get_market_regime()) or {}
    ev: list[Evidence] = []
    vix = snapshot_to_mapping(snap.get("vix")) or {}
    if vix.get("current") is not None:
        ev.append(Evidence(label="VIX", value=f"{float(vix['current']):.1f}"))
    fg = snapshot_to_mapping(snap.get("fear_greed")) or {}
    if fg.get("score") is not None:
        ev.append(
            Evidence(
                label="Fear & Greed index", value=f"{float(fg['score']):.0f} ({fg.get('rating')})"
            )
        )
    curve = snapshot_to_mapping(snap.get("yield_curve")) or {}
    if curve.get("spread_3m_10y") is not None:
        ev.append(
            Evidence(
                label="10-year minus 3-month Treasury yield",
                value=f"{float(curve['spread_3m_10y']):+.2f} points ({curve.get('status')})",
            )
        )
    try:
        ml = ml_regime.get_regime()
    except Exception:  # noqa: BLE001 - the regime model is optional context
        ml = {}
    if ml.get("regime"):
        ev.append(
            Evidence(label="Market risk-state (model)", value=str(ml.get("label") or ml["regime"]))
        )
    if not ev:
        raise ToolError("Market context is unavailable right now.")
    return ToolResult(
        summary="Current market context: " + "; ".join(f"{e.label} {e.value}" for e in ev) + ".",
        evidence=ev,
        provenance=Provenance(
            source="CBOE VIX, CNN Fear & Greed, US Treasury yields; MindMarket regime classifier",
            method="Latest published values; the risk-state is a classifier output, not a forecast",
            as_of=str(snap.get("as_of") or ml.get("as_of") or "") or None,
        ),
    )


def _accuracy(ctx: ToolContext, _: NoInput) -> ToolResult:
    from .. import stress_validation

    r = stress_validation.get_report()
    if r is None:
        raise ToolError("The validation report is unavailable.")
    m = r["conditional"]["models"]
    iv = r["conditional"]["interval"]
    ev = [
        Evidence(
            label="Typical error of the stress model",
            value=f"{m['seven_factor']['mae'] * 100:.1f} points",
        ),
        Evidence(label="Average bias", value=f"{m['seven_factor']['bias'] * 100:+.1f} points"),
        Evidence(
            label="Typical error assuming beta of 1",
            value=f"{m['beta_one']['mae'] * 100:.1f} points",
        ),
        Evidence(label="Outcomes tested", value=str(m["seven_factor"]["n"])),
        Evidence(
            label=f"{int(iv['nominal'] * 100)}% range contained the real outcome",
            value=f"{_upct(iv.get('coverage'), 0)} of the time",
        ),
    ]
    for p in r["rolling_var"]["pooled"]:
        ev.append(
            Evidence(
                label=f"{int(p['level'] * 100)}% VaR breach rate",
                value=f"{_upct(p['breach_rate'])} (expected {_upct(p['expected_rate'])})",
            )
        )
    return ToolResult(
        summary=f"Out of sample, the stress model's typical error is {m['seven_factor']['mae'] * 100:.1f} "
        f"points of return over {m['seven_factor']['n']} fund-portfolio outcomes; its "
        f"{int(iv['nominal'] * 100)}% range held {_upct(iv.get('coverage'), 0)} of the time, so its ranges are too narrow.",
        evidence=ev,
        provenance=Provenance(
            source=r["data"]["source"],
            method="Point-in-time backtest: loadings fitted only on data before each episode",
            as_of=r["data"]["last_date"],
            assumptions=r["caveats"][:2],
            warnings=[] if r["hash_verified"] else ["The report failed its integrity check."],
        ),
    )


# ── registry ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Callable[[ToolContext, Any], ToolResult]
    timeout_s: float = 45.0


REGISTRY: dict[str, ToolSpec] = {
    t.name: t
    for t in (
        ToolSpec(
            "portfolio_overview",
            "The user's account: net equity, leverage, largest positions, concentration, "
            "and how much of the book can be modelled. Call first for any portfolio question.",
            NoInput,
            _overview,
        ),
        ToolSpec(
            "factor_exposure",
            "The portfolio's sensitivity to the seven market factors and where its crisis "
            "volatility comes from.",
            NoInput,
            _exposure,
        ),
        ToolSpec(
            "run_stress_scenario",
            "Stress the portfolio under shocks the user describes (equity or Nasdaq move, "
            "yield change in bp, credit, dollar, oil, VIX multiple, gold). Returns P&L, "
            "per-factor contributions, option repricing and the margin effect.",
            StressInput,
            _stress,
        ),
        ToolSpec(
            "run_named_scenario",
            "Run one built-in scenario by id: a hypothetical (equity_crash, rates_up_200bp, "
            "credit_blowout, usd_spike, oil_spike, vol_spike, stagflation) or a historical "
            "one using the factor moves that actually happened.",
            NamedScenarioInput,
            _named,
        ),
        ToolSpec(
            "list_scenarios",
            "All built-in scenarios ranked by their effect on net equity. Use to find the worst cases.",
            NoInput,
            _scenarios,
        ),
        ToolSpec(
            "crisis_replay",
            "Replay the stock book through past crises using actual prices, with holdings "
            "that did not exist then reconstructed and labelled. Omit episode_id for all.",
            ReplayInput,
            _replay,
        ),
        ToolSpec(
            "loss_distribution",
            "Simulated loss distribution: VaR and CVaR over two weeks, in crisis or calm conditions.",
            DistributionInput,
            _distribution,
        ),
        ToolSpec(
            "compare_portfolio_change",
            "Compare the current book with a hypothetical change the USER described "
            "(e.g. halve a position). Only use changes the user asked about.",
            CompareInput,
            _compare,
        ),
        ToolSpec(
            "market_context",
            "Current market conditions: VIX, Fear & Greed, the yield curve, the regime model.",
            NoInput,
            _market,
            timeout_s=20.0,
        ),
        ToolSpec(
            "model_accuracy",
            "How accurate the stress model has been out of sample. Use when stating how far "
            "to trust a stress number.",
            NoInput,
            _accuracy,
            timeout_s=10.0,
        ),
    )
}


def tool_schemas() -> list[dict[str, Any]]:
    """Provider-neutral tool definitions (name, description, JSON schema)."""
    return [
        {
            "name": t.name,
            "description": t.description,
            "parameters": t.input_model.model_json_schema(),
        }
        for t in REGISTRY.values()
    ]


def execute(
    ctx: ToolContext, name: str, arguments: Any
) -> tuple[ToolResult, dict[str, Any], float]:
    """Validate and run one tool. Returns ``(result, validated_input, seconds)``.

    Never raises: an unknown tool, bad arguments, or a failure inside the tool
    becomes an ``ok=False`` result the model can read and the user can see.
    """
    started = time.perf_counter()
    spec = REGISTRY.get(name)
    if spec is None:
        return ToolResult(ok=False, summary="", error=f"Unknown tool: {str(name)[:40]}"), {}, 0.0
    try:
        args = spec.input_model.model_validate(arguments if isinstance(arguments, dict) else {})
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:4]
        )
        return ToolResult(ok=False, summary="", error=f"Invalid arguments: {problems}"), {}, 0.0
    validated = args.model_dump(exclude_none=True)
    try:
        result = spec.handler(ctx, args)
    except ToolError as exc:
        result = ToolResult(ok=False, summary="", error=str(exc))
    except ValueError as exc:
        # Service codes such as no_modelled_holdings: say what, not a stack.
        result = ToolResult(ok=False, summary="", error=f"Could not run: {str(exc)[:80]}")
    except Exception as exc:  # noqa: BLE001 - a tool failure must not end the run
        _log.warning("agent.tool_failed tool=%s err=%s", name, type(exc).__name__)
        result = ToolResult(ok=False, summary="", error="This analysis failed. Try again shortly.")
    return result, validated, time.perf_counter() - started
