"""Tests for app.execute_analysis() — quota-gate billing correctness.

These tests prove the gate logic in front of the (paid) risk pipeline:
  * Empty portfolio short-circuits BEFORE any quota call.
  * Admin bypass skips quota entirely.
  * QuotaExceeded surfaces an upgrade CTA, does NOT run the pipeline.
  * Generic quota-service failures fail CLOSED (no free billing).
  * ImportError on the billing module fails OPEN (deploy issue, never lock users out).
  * Unauth users get a sign-in warning, no pipeline.
  * invalidate_digest_cache is called on every fresh run so stale LLM summaries get dropped.

Everything past the quota gate (Monte-Carlo, RiskEngine, LLM calls) is mocked
or short-circuited via ``run_portfolio_analysis`` patches — we are *only*
testing the gate.

Importing ``app`` triggers ``st.set_page_config`` and other Streamlit side
effects at module load, so we install a fake ``streamlit`` module into
``sys.modules`` BEFORE the import happens (inside a fixture).
"""

from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest

# ── Fake streamlit infrastructure ──────────────────────────────────


class _SessionState(dict):
    """Dict that also supports attribute-style access (matches Streamlit's
    SessionStateProxy semantics that ``app.py`` relies on, e.g.
    ``st.session_state.analysis_ready = False``).
    """

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value

    def __delattr__(self, name):
        try:
            del self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def _make_fake_streamlit() -> MagicMock:
    """Build a MagicMock that quacks like the ``streamlit`` module."""
    fake = MagicMock(name="streamlit")
    fake.session_state = _SessionState()
    fake.secrets.get.return_value = ""

    # st.cache_data / st.cache_resource must return a decorator that returns
    # the underlying function unchanged — app.py applies these at import.
    def _passthrough_decorator(*d_args, **d_kwargs):
        def _wrap(fn):
            return fn

        # Support both @st.cache_data and @st.cache_data(ttl=...)
        if d_args and callable(d_args[0]) and not d_kwargs:
            return d_args[0]
        return _wrap

    fake.cache_data = _passthrough_decorator
    fake.cache_resource = _passthrough_decorator

    # st.stop raises like the real thing so a wayward code path is obvious.
    class _StopExecution(Exception):
        pass

    fake._StopExecution = _StopExecution

    def _stop():
        raise _StopExecution()

    fake.stop = _stop

    # st.query_params is dict-like and used during OAuth handler at import.
    fake.query_params = {}

    # st.columns(n) → iterable of MagicMock context managers. Without this,
    # landing-page rendering crashes on ``a, b, c = st.columns([1, 1, 2])``.
    def _columns(spec, *a, **kw):
        n = spec if isinstance(spec, int) else len(spec)
        return [MagicMock(name=f"col-{i}") for i in range(n)]

    fake.columns = _columns

    # st.tabs(labels) → iterable of MagicMock context managers.
    def _tabs(labels, *a, **kw):
        return [MagicMock(name=f"tab-{i}") for i, _ in enumerate(labels)]

    fake.tabs = _tabs

    # context manager-y things (st.spinner, st.sidebar, st.expander,
    # st.container) come for free from MagicMock.
    return fake


@pytest.fixture(scope="module")
def app_module():
    """Import ``app`` exactly once with a fake streamlit installed.

    Module-scoped because re-importing ``app`` is expensive (it pulls in
    plotly, pandas, the risk engine, etc.) and import-time side effects
    don't matter to the gate logic we're testing.
    """
    fake_st = _make_fake_streamlit()
    # Pre-seed the keys that app.py touches at module load via attribute
    # assignment so ``if "analysis_ready" not in st.session_state`` skips.
    fake_st.session_state["analysis_ready"] = False

    # Patch sys.modules BEFORE importing app.
    saved = sys.modules.get("streamlit")
    sys.modules["streamlit"] = fake_st

    # Aggressive sys.modules eviction. When the full test suite runs, an
    # earlier test will have imported these modules with the REAL streamlit.
    # If we leave them cached, `import app` re-uses the stale bindings —
    # error_handler.st stays bound to real streamlit, and when app.py's
    # error path calls error_handler.show_error(...) → real st.error()
    # without a ScriptRunContext → TypeError deep in the logging stack.
    # Pop every module whose source touches streamlit so the next
    # `import app` rebinds everything to our fake.
    _streamlit_dependent_prefixes = ("ui.", "pages.", "libs.auth.", "libs.billing.")
    _streamlit_dependent_modules = {
        "app",
        "error_handler",
        "shared_chat",
        "logging_config",
        "i18n",
    }
    for mod_name in list(sys.modules.keys()):
        if mod_name in _streamlit_dependent_modules or any(
            mod_name.startswith(p) for p in _streamlit_dependent_prefixes
        ):
            sys.modules.pop(mod_name, None)

    try:
        app = importlib.import_module("app")
    except Exception:
        # Restore on failure so unrelated tests aren't poisoned.
        if saved is not None:
            sys.modules["streamlit"] = saved
        else:
            sys.modules.pop("streamlit", None)
        raise

    # Stash the fake so individual tests can poke it.
    app._test_fake_st = fake_st  # type: ignore[attr-defined]
    yield app

    # Module-scope cleanup — leave the fake installed so other test files
    # that may also import app don't crash, but restore the original
    # streamlit if there was one.
    if saved is not None:
        sys.modules["streamlit"] = saved


@pytest.fixture(autouse=True)
def _reset_session_state(app_module):
    """Each test starts with a clean session_state."""
    fake_st = app_module._test_fake_st
    fake_st.session_state.clear()
    fake_st.session_state["analysis_ready"] = False
    # Reset the call records on the streamlit MagicMock methods used
    # for assertions (st.error, st.warning, st.info, st.success).
    for method in ("error", "warning", "info", "success", "markdown", "stop"):
        # ``stop`` is replaced by a real function above — keep it.
        attr = getattr(fake_st, method, None)
        if isinstance(attr, MagicMock):
            attr.reset_mock()
    yield


# ── Helpers ────────────────────────────────────────────────────────


def _short_circuit_pipeline(app_module):
    """Return a context manager that short-circuits the pipeline so we
    don't actually run Monte-Carlo / load market data when the gate
    *does* let execution through.

    We do this by replacing the runs after the gate — the easiest hook
    is ``st.stop`` (which is already patched to raise _StopExecution)
    and the high-level ``run_portfolio_analysis``."""
    return patch.object(
        app_module,
        "run_portfolio_analysis",
        side_effect=app_module._test_fake_st._StopExecution(),
    )


# ── Tests ──────────────────────────────────────────────────────────


def test_execute_analysis_skips_when_no_run_trigger(app_module):
    """No trigger + no force = no work, no quota call.

    When ``run_btn`` is False, execute_analysis falls through to the
    landing-page renderer, which calls ``st.stop()`` (modelled here by
    raising _StopExecution — same pattern Streamlit uses). The contract
    we care about: the quota was NEVER consulted, so no billing happened.
    """
    fake_st = app_module._test_fake_st
    fake_st.session_state["_run_trigger"] = False

    with patch("libs.billing.usage.check_quota") as mock_check_quota:
        try:
            app_module.execute_analysis(force=False)
        except fake_st._StopExecution:
            # Landing-page render → st.stop(); normal control flow.
            pass

    mock_check_quota.assert_not_called()
    # Empty portfolio gate, admin gate, current_user — none should fire.
    fake_st.error.assert_not_called()


def test_execute_analysis_runs_when_force_true(app_module):
    """force=True must enter the gated branch even without _run_trigger.

    We patch admin mode ON so the gate lets us through, then short-circuit
    the actual pipeline so we don't run a real risk engine. Reaching the
    pipeline at all proves the gate accepted force=True.
    """
    fake_st = app_module._test_fake_st
    fake_st.session_state["_run_trigger"] = False
    fake_st.session_state["weights_input"] = '{"AAPL": 1.0}'

    with (
        patch.dict("os.environ", {"MINDMARKET_ADMIN_MODE": "true"}),
        patch("libs.auth.active_portfolio.is_active_portfolio_empty", return_value=False),
        patch.object(app_module, "_reload_portfolio_config", return_value=({}, 0.0)),
        patch.object(
            app_module,
            "run_portfolio_analysis",
            side_effect=app_module._test_fake_st._StopExecution(),
        ) as mock_run,
    ):
        # The pipeline call raises StopExecution — that proves we reached
        # past the gate, which is the assertion we want.
        with pytest.raises(app_module._test_fake_st._StopExecution):
            app_module.execute_analysis(force=True)

        mock_run.assert_called_once()


def test_execute_analysis_blocks_empty_portfolio_before_quota(app_module):
    """Empty portfolio → warn and return False BEFORE check_quota fires.

    This is critical: an authed user with no portfolio rows must not be
    silently analyzed against the dev's hardcoded fallback holdings, and
    must not consume one of their monthly analysis credits in the process.
    """
    fake_st = app_module._test_fake_st
    fake_st.session_state["_run_trigger"] = True

    with (
        patch(
            "libs.auth.active_portfolio.is_active_portfolio_empty",
            return_value=True,
        ),
        patch("libs.billing.usage.check_quota") as mock_check_quota,
        patch("libs.auth.session.current_user", return_value={"id": "u1", "email": "x@y.com"}),
    ):
        result = app_module.execute_analysis(force=False)

    assert result is False
    mock_check_quota.assert_not_called()
    # We should have shown a warning, not an error.
    fake_st.warning.assert_called()
    fake_st.error.assert_not_called()


def test_execute_analysis_admin_bypasses_quota(app_module, monkeypatch):
    """MINDMARKET_ADMIN_MODE=true → check_quota is never imported/called."""
    fake_st = app_module._test_fake_st
    fake_st.session_state["_run_trigger"] = True
    fake_st.session_state["weights_input"] = '{"AAPL": 1.0}'

    monkeypatch.setenv("MINDMARKET_ADMIN_MODE", "true")

    with (
        patch("libs.auth.active_portfolio.is_active_portfolio_empty", return_value=False),
        patch("libs.billing.usage.check_quota") as mock_check_quota,
        patch("libs.auth.session.current_user") as mock_current_user,
        patch.object(app_module, "_reload_portfolio_config", return_value=({}, 0.0)),
        patch.object(
            app_module,
            "run_portfolio_analysis",
            side_effect=app_module._test_fake_st._StopExecution(),
        ),
    ):
        with pytest.raises(app_module._test_fake_st._StopExecution):
            app_module.execute_analysis(force=False)

    mock_check_quota.assert_not_called()
    mock_current_user.assert_not_called()


def test_execute_analysis_quota_exceeded_shows_cta(app_module, monkeypatch):
    """QuotaExceeded → st.error with mailto CTA, return False, no pipeline."""
    fake_st = app_module._test_fake_st
    fake_st.session_state["_run_trigger"] = True
    fake_st.session_state["weights_input"] = '{"AAPL": 1.0}'

    monkeypatch.delenv("MINDMARKET_ADMIN_MODE", raising=False)

    from libs.billing.usage import QuotaExceeded

    qe = QuotaExceeded(kind="analysis", limit=2, used=2, plan="free")

    with (
        patch("libs.auth.active_portfolio.is_active_portfolio_empty", return_value=False),
        patch("libs.auth.session.current_user", return_value={"id": "u1", "email": "x@y.com"}),
        patch("libs.billing.usage.check_quota", side_effect=qe),
        patch.object(app_module, "run_portfolio_analysis") as mock_run,
    ):
        result = app_module.execute_analysis(force=False)

    assert result is False
    mock_run.assert_not_called()
    fake_st.error.assert_called_once()
    err_text = fake_st.error.call_args[0][0]
    assert "contact@mindmarket.app" in err_text


def test_execute_analysis_quota_service_fails_closed(app_module, monkeypatch):
    """Generic Exception from check_quota → fail CLOSED.

    Don't burn a Monte-Carlo + LLM digest on a user we can't reliably bill.
    """
    fake_st = app_module._test_fake_st
    fake_st.session_state["_run_trigger"] = True
    fake_st.session_state["weights_input"] = '{"AAPL": 1.0}'

    monkeypatch.delenv("MINDMARKET_ADMIN_MODE", raising=False)

    with (
        patch("libs.auth.active_portfolio.is_active_portfolio_empty", return_value=False),
        patch("libs.auth.session.current_user", return_value={"id": "u1", "email": "x@y.com"}),
        patch("libs.billing.usage.check_quota", side_effect=RuntimeError("db unreachable")),
        patch.object(app_module, "run_portfolio_analysis") as mock_run,
    ):
        result = app_module.execute_analysis(force=False)

    assert result is False
    mock_run.assert_not_called()
    fake_st.error.assert_called_once()
    err_text = fake_st.error.call_args[0][0]
    assert "temporarily unavailable" in err_text


def test_execute_analysis_quota_module_missing_fails_open(app_module, monkeypatch):
    """ImportError on libs.billing.usage → fail OPEN.

    Background: the previous code structure had imports + `except
    QuotaExceeded` in the same try block. When the import failed, Python
    evaluated `except QuotaExceeded` against the active exception, found
    `QuotaExceeded` unbound (the import never completed), and raised
    UnboundLocalError before reaching `except ImportError: pass`. Real
    deploy-config gap → every authed user 500'd.

    Fix (commit pairing this test): imports live in their OWN try-block
    with `except ImportError: pass`, then a nested `else` runs the quota
    call with `except QuotaExceeded` / `except Exception`. The import
    branch now actually works.

    This test now exercises the FIXED path: import fails → quota gate
    silently skipped → pipeline proceeds (mocked to short-circuit).
    """
    fake_st = app_module._test_fake_st
    fake_st.session_state["_run_trigger"] = True
    fake_st.session_state["weights_input"] = '{"AAPL": 1.0}'

    monkeypatch.delenv("MINDMARKET_ADMIN_MODE", raising=False)

    import builtins

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        # Match the multi-name import: `from libs.billing.usage import
        # QuotaExceeded, check_quota`. Python passes `libs.billing.usage`
        # as `name`. Raise so the entire `from ... import ...` fails.
        if name == "libs.billing.usage":
            raise ImportError("billing module unavailable")
        return real_import(name, globals, locals, fromlist, level)

    StopExec = app_module._test_fake_st._StopExecution

    with (
        patch("libs.auth.active_portfolio.is_active_portfolio_empty", return_value=False),
        patch.object(builtins, "__import__", side_effect=fake_import),
        patch.object(app_module, "_reload_portfolio_config", return_value=({}, 0.0)),
        patch.object(app_module, "run_portfolio_analysis", side_effect=StopExec()),
    ):
        # Same pattern as test_execute_analysis_admin_bypasses_quota:
        # reaching run_portfolio_analysis is the proof. app.py catches
        # the sentinel via its outer `except Exception`, shows an
        # "Analysis Failed" toast, then calls st.stop() which re-raises
        # _StopExecution — pytest.raises catches the re-raise.
        with pytest.raises(StopExec):
            app_module.execute_analysis(force=False)

    # The quota-specific fail-CLOSED toast must NOT appear — that string
    # belongs to the fail-CLOSED path which we explicitly didn't take
    # (the ImportError fail-OPEN branch silently passed through).
    quota_error_calls = [
        c for c in fake_st.error.call_args_list if "Quota service temporarily unavailable" in str(c)
    ]
    assert (
        quota_error_calls == []
    ), f"Quota fail-closed toast leaked into fail-open path: {quota_error_calls}"


def test_execute_analysis_unauth_user_warns_and_stops(app_module, monkeypatch):
    """current_user() returns None + non-admin → warn, return False."""
    fake_st = app_module._test_fake_st
    fake_st.session_state["_run_trigger"] = True
    fake_st.session_state["weights_input"] = '{"AAPL": 1.0}'

    monkeypatch.delenv("MINDMARKET_ADMIN_MODE", raising=False)

    with (
        patch("libs.auth.active_portfolio.is_active_portfolio_empty", return_value=False),
        patch("libs.auth.session.current_user", return_value=None),
        patch("libs.billing.usage.check_quota") as mock_check_quota,
        patch.object(app_module, "run_portfolio_analysis") as mock_run,
    ):
        result = app_module.execute_analysis(force=False)

    assert result is False
    mock_check_quota.assert_not_called()
    mock_run.assert_not_called()
    fake_st.warning.assert_called()
    # Warning text references signing in.
    warn_text = fake_st.warning.call_args[0][0]
    assert "sign in" in warn_text.lower()


def test_execute_analysis_invalidates_digest_cache_on_new_run(app_module):
    """A fresh run must drop every cached LLM digest so users see new
    commentary aligned with the new report."""
    fake_st = app_module._test_fake_st
    fake_st.session_state["_run_trigger"] = True
    fake_st.session_state["weights_input"] = '{"AAPL": 1.0}'
    stale_key = "_llm_cache::test::1234"
    fake_st.session_state[stale_key] = "stale"
    fake_st.session_state["_llm_cache_keys"] = {stale_key}

    with (
        patch.dict("os.environ", {"MINDMARKET_ADMIN_MODE": "true"}),
        patch("libs.auth.active_portfolio.is_active_portfolio_empty", return_value=False),
        patch.object(app_module, "_reload_portfolio_config", return_value=({}, 0.0)),
        patch.object(
            app_module,
            "run_portfolio_analysis",
            side_effect=app_module._test_fake_st._StopExecution(),
        ),
    ):
        try:
            app_module.execute_analysis(force=False)
        except app_module._test_fake_st._StopExecution:
            pass

    # The digest invalidator should have removed the cache slot AND emptied
    # the key registry — even if the pipeline subsequently exploded.
    assert stale_key not in fake_st.session_state
    assert fake_st.session_state.get("_llm_cache_keys", set()) == set()
