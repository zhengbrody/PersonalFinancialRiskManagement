"""scripts/ml_health_alerts.py — one alert kind per independent failure, with
`unknown` never paging and never auto-resolving."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "ml_health_alerts", ROOT / "scripts" / "ml_health_alerts.py"
)
alerts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(alerts)


def _health(**data):
    base = {
        "status": "ok",
        "overall_status": "healthy",
        "freshness": {"status": "fresh", "age_days": 3.0, "threshold_days": 21.0},
        "approved_artifact": {"match": True},
    }
    base.update(data)
    return {"data": base}


OK_RUN = {"conclusion": "success", "url": "u"}


def states(out):
    return {k: v["state"] for k, v in out.items()}


def test_all_healthy_is_all_ok():
    assert set(states(alerts.classify(_health(), OK_RUN)).values()) == {"ok"}


def test_each_kind_fires_independently():
    assert states(alerts.classify(_health(overall_status="drift"), OK_RUN))["drift"] == "firing"
    assert (
        states(alerts.classify(_health(freshness={"status": "stale"}), OK_RUN))["freshness"]
        == "firing"
    )
    assert (
        states(alerts.classify(_health(approved_artifact={"match": False}), OK_RUN))["artifact"]
        == "firing"
    )
    out = alerts.classify(_health(), {"conclusion": "failure", "url": "u"})
    assert states(out)["train_pipeline"] == "firing"
    assert states(out)["drift"] == "ok"  # one failure doesn't colour the others


def test_stale_model_does_not_fire_drift():
    out = states(alerts.classify(_health(freshness={"status": "stale"}), OK_RUN))
    assert out["drift"] == "ok"


def test_unknowns_never_fire_or_resolve():
    out = states(
        alerts.classify(
            _health(
                status="not_ready",
                overall_status=None,
                freshness={"status": "unknown"},
                approved_artifact={"match": None},
            ),
            None,
        )
    )
    assert out == {
        "endpoint": "ok",
        "drift": "unknown",
        "freshness": "unknown",
        "artifact": "unknown",
        "train_pipeline": "unknown",
    }


def test_watch_band_is_not_a_page():
    assert states(alerts.classify(_health(overall_status="watch"), OK_RUN))["drift"] == "ok"


def test_failed_probe_fires_endpoint_only():
    out = states(alerts.classify(None, OK_RUN))
    assert out["endpoint"] == "firing"
    assert out["drift"] == out["freshness"] == out["artifact"] == "unknown"


def test_drift_title_is_the_pre_dedupe_title():
    # An already-open issue from the old workflow must be reused, not duplicated.
    assert alerts.TITLES["drift"] == "ML drift monitor FAILED (/api/v1/ml/health)"
    assert len(set(alerts.TITLES.values())) == len(alerts.TITLES)


def test_cli_accepts_gh_run_list_and_empty_probe(tmp_path, capsys):
    health = tmp_path / "h.json"
    health.write_text("")  # failed probe
    run = tmp_path / "r.json"
    run.write_text(json.dumps([{"conclusion": "failure", "url": "u"}]))
    assert alerts.main(["--health", str(health), "--train-run", str(run)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["endpoint"]["state"] == "firing"
    assert out["train_pipeline"]["state"] == "firing"
