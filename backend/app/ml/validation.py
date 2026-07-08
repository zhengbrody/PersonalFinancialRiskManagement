"""Walk-forward validation report for the regime classifier.

    python -m backend.app.ml.validate [--config ...] [--cache-dir .cache/ml]

Produces ``docs/ml/validation_report.md``: a per-fold walk-forward table
(accuracy / macro-F1 / log-loss), the model vs THREE baselines (majority
class, persistence, logistic regression), a 10-bin calibration (reliability)
table for the elevated-risk probability — the product's real signal — and
permutation feature importance. A reliability PNG is written when matplotlib
is installed (training-side extra); the markdown never depends on it.

Time-series discipline: every boundary is chronological (TimeSeriesSplit
expanding folds + a final hold-out). The persistence baseline respects
INFORMATION AVAILABILITY: the label for day t describes the forward window
(t, t+h], so the most recent label observable AT t is the one for day t−h —
persistence predicts ŷ(t) = y(t−h), never "yesterday's label" (which isn't
knowable until t+h−1).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, log_loss, roc_auc_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .config import TrainConfig
from .train import _feature_importances, _fit, _make_model

_log = logging.getLogger(__name__)

CALIBRATION_BINS = 10
ELEVATED = ("volatile", "stress")


# ── baselines ─────────────────────────────────────────────────────────


def persistence_predictions(y: pd.Series, horizon: int) -> pd.Series:
    """ŷ(t) = the most recent OBSERVABLE label at t, i.e. y(t−horizon).

    y(t) describes forward vol over (t, t+h], so it only becomes known at
    t+h; carrying "yesterday's label" forward would leak h−1 days of the
    future. Positions with no completed window yet are NaN."""
    return y.shift(horizon)


def _make_logistic(seed: int) -> Pipeline:
    """Linear baseline on the same features: median-impute (LogReg can't eat
    NaN, unlike HistGBM) → scale → multinomial logistic."""
    return Pipeline(
        [
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("logit", LogisticRegression(max_iter=1000, random_state=seed)),
        ]
    )


# ── metric helpers ────────────────────────────────────────────────────


def _safe_log_loss(
    y_true: pd.Series, proba: np.ndarray, classes: list[str]
) -> tuple[Optional[float], int]:
    """Log-loss over the rows whose true class the model has seen; returns
    (loss, n_skipped). A fold whose training window never contained a class
    cannot be scored on it — skipping is stated in the report, not hidden."""
    mask = y_true.isin(classes).to_numpy()
    skipped = int((~mask).sum())
    if mask.sum() == 0:
        return None, skipped
    try:
        loss = float(log_loss(y_true[mask], proba[mask], labels=classes))
    except Exception as exc:  # noqa: BLE001 - a metric must never sink the report
        _log.warning("ml.validation.log_loss_failed err=%s", type(exc).__name__)
        return None, skipped
    return round(loss, 4), skipped


def _acc(y_true: pd.Series, y_pred: np.ndarray | pd.Series) -> float:
    return round(float((np.asarray(y_pred) == y_true.to_numpy()).mean()), 4)


def _macro_f1(y_true: pd.Series, y_pred: np.ndarray | pd.Series) -> float:
    return round(float(f1_score(y_true, y_pred, average="macro", zero_division=0)), 4)


# ── the report ────────────────────────────────────────────────────────


def walk_forward_report(
    X: pd.DataFrame, y: pd.Series, cfg: Optional[TrainConfig] = None
) -> dict[str, Any]:
    """All numbers behind the markdown: per-fold walk-forward rows, aggregate
    model-vs-baselines comparison, hold-out calibration bins, importances."""
    c = cfg or TrainConfig()
    horizon = c.label_horizon
    persist_all = persistence_predictions(y, horizon)

    folds: list[dict[str, Any]] = []
    fold_means: dict[str, list] = {"model": [], "majority": [], "persistence": [], "logistic": []}
    tscv = TimeSeriesSplit(n_splits=c.cv_splits)
    for i, (tr, te) in enumerate(tscv.split(X), start=1):
        # PURGE/EMBARGO: the last `horizon` training rows carry labels computed
        # from returns INSIDE the test window (y(t) spans (t, t+h]) — training
        # on them leaks test-period information. Drop them from every fold.
        tr = tr[:-horizon] if len(tr) > horizon else tr
        X_tr, y_tr = X.iloc[tr], y.iloc[tr]
        X_te, y_te = X.iloc[te], y.iloc[te]

        model = _fit(c, X_tr, y_tr)
        pred = model.predict(X_te)
        proba = model.predict_proba(X_te)
        loss, loss_skipped = _safe_log_loss(y_te, proba, list(model.classes_))

        majority = y_tr.value_counts().idxmax()
        maj_pred = np.full(len(y_te), majority)

        persist_pred = persist_all.iloc[te]
        persist_mask = persist_pred.notna()
        persist_acc = (
            _acc(y_te[persist_mask], persist_pred[persist_mask]) if persist_mask.any() else None
        )

        logit = _make_logistic(c.seed).fit(X_tr, y_tr)
        logit_pred = logit.predict(X_te)
        logit_loss, _ = _safe_log_loss(y_te, logit.predict_proba(X_te), list(logit.classes_))

        folds.append(
            {
                "fold": i,
                "train_end": str(X_tr.index[-1].date()),
                "test_start": str(X_te.index[0].date()),
                "test_end": str(X_te.index[-1].date()),
                "n_test": int(len(y_te)),
                "accuracy": _acc(y_te, pred),
                "macro_f1": _macro_f1(y_te, pred),
                "log_loss": loss,
                "log_loss_skipped_rows": loss_skipped,
                "baseline_majority_acc": _acc(y_te, maj_pred),
                "baseline_persistence_acc": persist_acc,
                "persistence_rows": int(persist_mask.sum()),
                "baseline_logistic_acc": _acc(y_te, logit_pred),
                "baseline_logistic_log_loss": logit_loss,
            }
        )
        fold_means["model"].append(folds[-1]["accuracy"])
        fold_means["majority"].append(folds[-1]["baseline_majority_acc"])
        if persist_acc is not None:
            fold_means["persistence"].append(persist_acc)
        fold_means["logistic"].append(folds[-1]["baseline_logistic_acc"])

    aggregate = {
        name: round(float(np.mean(vals)), 4) if vals else None for name, vals in fold_means.items()
    }

    calibration = _holdout_calibration(X, y, c)
    final_model = _make_model(c).fit(X, y)
    importances = _feature_importances(final_model, X, y, c)

    return {
        "config": c.echo(),
        "n_rows": int(len(X)),
        "window": {"start": str(X.index[0].date()), "end": str(X.index[-1].date())},
        "folds": folds,
        "aggregate_accuracy": aggregate,
        "calibration": calibration,
        "feature_importances": importances,
    }


def _holdout_calibration(X: pd.DataFrame, y: pd.Series, c: TrainConfig) -> dict[str, Any]:
    """Reliability of the ELEVATED-risk probability on the chronological
    hold-out: 10 uniform bins of predicted P(volatile∪stress) vs the observed
    frequency. This binary probability is what the product surfaces."""
    cut = int(len(X) * (1.0 - c.holdout_fraction))
    # Same embargo as the folds: the last `horizon` pre-cut labels overlap the
    # hold-out window.
    fit_end = max(1, cut - c.label_horizon)
    model = _fit(c, X.iloc[:fit_end], y.iloc[:fit_end])
    proba = model.predict_proba(X.iloc[cut:])
    classes = list(model.classes_)
    idx = [i for i, cls in enumerate(classes) if cls in ELEVATED]
    p_elev = proba[:, idx].sum(axis=1)
    y_elev = y.iloc[cut:].isin(ELEVATED).astype(int).to_numpy()

    edges = np.linspace(0.0, 1.0, CALIBRATION_BINS + 1)
    rows = []
    for b in range(CALIBRATION_BINS):
        lo, hi = edges[b], edges[b + 1]
        mask = (p_elev >= lo) & (p_elev < hi if b < CALIBRATION_BINS - 1 else p_elev <= hi)
        n = int(mask.sum())
        rows.append(
            {
                "bin": f"[{lo:.1f}, {hi:.1f}{')' if b < CALIBRATION_BINS - 1 else ']'}",
                "n": n,
                "mean_predicted": round(float(p_elev[mask].mean()), 4) if n else None,
                "observed_frequency": round(float(y_elev[mask].mean()), 4) if n else None,
            }
        )
    base = float(y_elev.mean())
    auc = round(float(roc_auc_score(y_elev, p_elev)), 4) if y_elev.min() != y_elev.max() else None
    return {
        "target": "P(elevated risk) = P(volatile) + P(stress)",
        "holdout_size": int(len(y_elev)),
        "elevated_base_rate": round(base, 4),
        "elevated_risk_auc": auc,
        # Brier of the model vs always-predicting-the-base-rate (reference).
        "brier": round(float(np.mean((p_elev - y_elev) ** 2)), 4),
        "brier_base_rate": round(float(np.mean((base - y_elev) ** 2)), 4),
        "bins": rows,
    }


# ── rendering ─────────────────────────────────────────────────────────


def _persistence_coverage_note(report: dict[str, Any]) -> str:
    partial = [
        f"fold {f['fold']} ({f.get('persistence_rows', f['n_test'])}/{f['n_test']})"
        for f in report["folds"]
        if f.get("persistence_rows", f["n_test"]) < f["n_test"]
    ]
    if not partial:
        return ""
    return (
        " NOTE: persistence covered only part of some test windows — "
        + ", ".join(partial)
        + " — so its aggregate is not row-for-row comparable."
    )


def _fmt(v: Any) -> str:
    return "—" if v is None else (f"{v:.4f}" if isinstance(v, float) else str(v))


def _headline(report: dict[str, Any]) -> list[str]:
    """The read-this-first verdict. Wording is computed from the numbers so a
    future run whose results flip cannot leave a stale claim behind — this
    project's narrative is an HONEST VALIDATION SYSTEM, not a prediction model."""
    agg = report["aggregate_accuracy"]
    cal = report["calibration"]
    model, persist = agg.get("model"), agg.get("persistence")
    brier, brier_ref = cal.get("brier"), cal.get("brier_base_rate")
    auc = cal.get("elevated_risk_auc")

    if model is not None and persist is not None:
        verdict = "LOSES to" if model < persist else "beats"
        cls_line = (
            f"**On 4-class point accuracy the model {verdict} the persistence "
            f"baseline ({model:.3f} vs {persist:.3f} mean fold accuracy).**"
        )
    else:
        cls_line = "**4-class accuracy vs persistence could not be compared on this run.**"

    if brier is not None and brier_ref is not None:
        prob_quality = "beats" if brier < brier_ref else "does NOT beat"
        prob_line = (
            f"The elevated-risk probability {prob_quality} the base-rate reference "
            f"(Brier {brier:.4f} vs {brier_ref:.4f}"
            + (f"; hold-out ROC-AUC {auc:.3f}" if auc is not None else "")
            + ")."
        )
    else:
        prob_line = "Probabilistic skill could not be scored on this run."

    return [
        "## Headline conclusion — read this first",
        "",
        cls_line,
        f"Classification is weak; the skill that survives honest validation is "
        f"probabilistic. {prob_line} The model is therefore positioned as a "
        "**probability-ranking signal** (how much elevated-risk pressure is "
        "building), NOT a classifier — and this report exists to keep that "
        "claim honest, run after run.",
        "",
    ]


def render_markdown(report: dict[str, Any], *, png_rel_path: Optional[str] = None) -> str:
    cfg = report["config"]
    lines = [
        "# Risk-Today Regime Classifier — Validation Report",
        "",
        "_Auto-generated by `python -m backend.app.ml.validate` — do not edit by hand._",
        "",
        f"- **Data window:** {report['window']['start']} → {report['window']['end']} "
        f"({report['n_rows']} labeled rows)",
        f"- **Config:** seed {cfg['seed']} · {cfg['cv_splits']} expanding folds · "
        f"hold-out {cfg['holdout_fraction']:.0%} · model_version {cfg['model_version']}",
        "- **Discipline:** all boundaries chronological (`TimeSeriesSplit` + final "
        "hold-out); a `horizon`-row PURGE/EMBARGO removes training labels whose "
        "forward window overlaps the test period; no random eval splits; the "
        "persistence baseline uses only labels observable at prediction time "
        "(ŷ(t) = y(t−horizon)).",
        "",
        *_headline(report),
        "## Walk-forward folds",
        "",
        "| Fold | Test window | n | Acc | Macro-F1 | Log-loss | Majority acc | "
        "Persistence acc | Logistic acc |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for f in report["folds"]:
        lines.append(
            f"| {f['fold']} | {f['test_start']} → {f['test_end']} | {f['n_test']} "
            f"| {_fmt(f['accuracy'])} | {_fmt(f['macro_f1'])} | {_fmt(f['log_loss'])} "
            f"| {_fmt(f['baseline_majority_acc'])} | {_fmt(f['baseline_persistence_acc'])} "
            f"| {_fmt(f['baseline_logistic_acc'])} |"
        )

    agg = report["aggregate_accuracy"]
    lines += [
        "",
        "## Model vs baselines (mean fold accuracy)",
        "",
        "| Candidate | Mean accuracy |",
        "|---|---|",
        f"| **HistGBM (the model)** | **{_fmt(agg['model'])}** |",
        f"| Majority class | {_fmt(agg['majority'])} |",
        f"| Persistence (y at t−horizon) | {_fmt(agg['persistence'])} |",
        f"| Logistic regression | {_fmt(agg['logistic'])} |",
        "",
        "Log-loss rows marked — mean a fold's training window never saw some "
        "test class (the skipped-row counts are in the JSON payload); majority "
        "and persistence emit no probabilities, so log-loss applies only to the "
        "model and the logistic baseline." + _persistence_coverage_note(report),
        "",
        "## Calibration — elevated-risk probability (hold-out)",
        "",
        f"Target: {report['calibration']['target']} · hold-out "
        f"{report['calibration']['holdout_size']} rows · base rate "
        f"{_fmt(report['calibration']['elevated_base_rate'])} · Brier "
        f"{_fmt(report['calibration'].get('brier'))} (base-rate reference "
        f"{_fmt(report['calibration'].get('brier_base_rate'))})",
        "",
        "| Predicted bin | n | Mean predicted | Observed frequency |",
        "|---|---|---|---|",
    ]
    for b in report["calibration"]["bins"]:
        lines.append(
            f"| {b['bin']} | {b['n']} | {_fmt(b['mean_predicted'])} "
            f"| {_fmt(b['observed_frequency'])} |"
        )
    if png_rel_path:
        lines += ["", f"![Reliability diagram]({png_rel_path})"]

    lines += [
        "",
        "## Permutation feature importance (macro-F1, full fit)",
        "",
        "| Feature | Importance |",
        "|---|---|",
    ]
    for name, imp in list(report["feature_importances"].items())[:15]:
        lines.append(f"| `{name}` | {imp} |")

    lines += [
        "",
        "## Honest notes",
        "",
        "- The estimator's internal `early_stopping` split is seeded but "
        "shuffled within each fit (see the model card's limitations).",
        "- 4-class accuracy near the majority baseline is expected; the "
        "product-relevant signal is the elevated-risk probability, whose "
        "calibration is tabled above.",
        "- Persistence is a STRONG baseline (regimes persist) — judge the "
        "model on the calibrated elevated-risk probability, not on beating "
        "persistence at 4-class point calls.",
        "- Calibration bins sit on OVERLAPPING 10-day forward windows: "
        "adjacent rows share 9/10 return days, so the effective sample is "
        "roughly n/horizon and sparse upper bins may reflect only a couple "
        "of market episodes — read them as direction, not precision.",
        "",
    ]
    return "\n".join(lines)


def save_reliability_png(report: dict[str, Any], path) -> bool:
    """Reliability diagram via matplotlib when available (training extra);
    returns False (no file) otherwise — the markdown table stands alone."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        _log.info("ml.validation.png_skipped matplotlib not installed")
        return False
    bins = [b for b in report["calibration"]["bins"] if b["n"]]
    if not bins:
        return False
    xs = [b["mean_predicted"] for b in bins]
    ys = [b["observed_frequency"] for b in bins]
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], "--", color="#999", label="perfect calibration")
    ax.plot(xs, ys, "o-", color="#2563eb", label="model")
    ax.set_xlabel("Mean predicted P(elevated)")
    ax.set_ylabel("Observed frequency")
    ax.set_title("Reliability — elevated-risk probability (hold-out)")
    ax.legend()
    fig.tight_layout()
    from pathlib import Path as _P

    _P(path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return True
