"""Readiness reports must never turn skipped/external checks into green gates."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from scripts import run_copilot_predeploy_checks as runner


def test_default_only_reports_plan_and_external_blockers(monkeypatch, capsys):
    monkeypatch.setattr(runner, "execute", lambda _: pytest.fail("Must not execute by default"))
    assert runner.main([]) == 0
    result = json.loads(capsys.readouterr().out)
    assert not result["deployment_performed"] and not result["production_flags_changed"]
    assert all(row["status"] == "skipped" for row in result["checks"][:-3])
    assert all(row["status"] == "blocked" for row in result["checks"][-3:])


def test_bounded_repeats_stop_at_failure_and_never_print_child_output(monkeypatch, capsys):
    calls = []

    def execute(check):
        calls.append(check.name)
        return {"name": check.name, "status": "passed" if len(calls) == 1 else "blocked"}

    monkeypatch.setattr(runner, "execute", execute)
    assert runner.main(["--run", "auth_migrations", "--soak-repeats", "3"]) == 1
    assert calls == ["auth_migrations", "auth_migrations"]
    assert "secret" not in capsys.readouterr().out


def test_subprocess_output_is_discarded_and_errors_are_not_serialized():
    def execute(command, **kwargs):
        assert kwargs["stdout"] is subprocess.DEVNULL
        assert kwargs["stderr"] is subprocess.DEVNULL
        assert "env" not in kwargs
        raise OSError("secret token must never enter report")

    result = runner.execute(runner.Check("fixture", ("fixture",)), runner=execute)
    assert result["status"] == "blocked"
    assert "secret" not in json.dumps(result)


def test_success_and_nonzero_exit_are_distinguished():
    check = runner.Check("fixture", ("fixture",))
    assert (
        runner.execute(check, runner=lambda *a, **k: SimpleNamespace(returncode=0))["status"]
        == "passed"
    )
    assert (
        runner.execute(check, runner=lambda *a, **k: SimpleNamespace(returncode=1))["status"]
        == "blocked"
    )


def test_arbitrary_command_or_unbounded_soak_rejected():
    for args in (
        ["--run", "deploy"],
        ["--run", "auth_migrations", "--soak-repeats", "100"],
        ["--soak-repeats", "2"],
    ):
        with pytest.raises(SystemExit):
            runner.main(args)
