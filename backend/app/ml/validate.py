"""CLI entry: ``python -m backend.app.ml.validate`` → validation report.

Fetches history (cache-aware, same flags as train), runs the walk-forward
report, and writes ``docs/ml/validation_report.md`` (+ a reliability PNG
under docs/ml/assets/ when matplotlib is installed). Offline-safe pieces
live in validation.py; this module is just argument plumbing + file IO.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from . import data as ml_data
from . import train as ml_train
from .config import load_config
from .validation import render_markdown, save_reliability_png, walk_forward_report

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT = _REPO_ROOT / "docs" / "ml" / "validation_report.md"
DEFAULT_ASSETS = _REPO_ROOT / "docs" / "ml" / "assets"


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Walk-forward validation report.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--cache-dir", default=None)
    parser.add_argument("--years", type=float, default=None)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--assets-dir", default=str(DEFAULT_ASSETS))
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    years = args.years if args.years is not None else cfg.years
    raw = ml_data.fetch_history(years=years, cache_dir=args.cache_dir)
    X, y = ml_train.build_dataset(raw)

    report = walk_forward_report(X, y, cfg)

    out = Path(args.out)
    png_path = Path(args.assets_dir) / "reliability_elevated_risk.png"
    png_written = save_reliability_png(report, png_path)
    png_rel = None
    if png_written:
        try:
            png_rel = str(png_path.relative_to(out.parent))
        except ValueError:
            png_rel = str(png_path)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_markdown(report, png_rel_path=png_rel))
    (out.parent / "validation_report.json").write_text(json.dumps(report, indent=2))

    agg = report["aggregate_accuracy"]
    print(f"\n=== validation report → {out} ===")
    print(f"  folds: {len(report['folds'])}  rows: {report['n_rows']}")
    print(
        f"  mean fold acc — model {agg['model']} | majority {agg['majority']} "
        f"| persistence {agg['persistence']} | logistic {agg['logistic']}"
    )
    print(
        f"  calibration bins: {sum(1 for b in report['calibration']['bins'] if b['n'])}/10 populated"
    )
    print(f"  reliability png: {'written' if png_written else 'skipped (no matplotlib)'}")


if __name__ == "__main__":
    main()
