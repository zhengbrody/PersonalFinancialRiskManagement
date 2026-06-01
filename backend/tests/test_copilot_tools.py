"""Unit tests for the Copilot tool-use layer.

Two surfaces under test, both fully hermetic:

  * ``services.copilot_tools.execute_tool`` — each tool branch with the
    underlying free data fn monkeypatched (success + raising → fail-soft).
  * ``services.llm_client`` tool-use loop — a fake Anthropic client that
    emits one ``tool_use`` block then an ``end_turn`` text block, proving
    ``execute_tool`` runs and the final text is returned. Plus the
    degrade-to-None contract (no key) and ``with_tools`` default parity.

No network, no SDK, no Anthropic key required.
"""

from __future__ import annotations

import json

import pandas as pd

from backend.app.services import copilot_tools as ct

# ── execute_tool: market sentiment ─────────────────────────────────────


def test_market_sentiment_compact(monkeypatch):
    import market_intelligence as mi

    monkeypatch.setattr(
        mi, "get_vix_current", lambda: {"current": 18.2, "change": 0.05, "level": "Normal"}
    )
    monkeypatch.setattr(
        mi, "fetch_fear_greed", lambda: {"score": 55.0, "rating": "greed", "extra": "x"}
    )
    monkeypatch.setattr(
        mi,
        "fetch_yield_curve",
        lambda: (pd.DataFrame(), {"curve_status": "Inverted", "3M-10Y Spread": -0.42}),
    )

    out = ct.execute_tool("get_market_sentiment", {})
    data = json.loads(out)
    assert data["vix"]["current"] == 18.2
    assert data["vix"]["level"] == "Normal"
    assert data["fear_greed"] == {"score": 55.0, "rating": "greed"}
    assert data["yield_curve"]["curve_status"] == "Inverted"
    assert data["yield_curve"]["spread_3m_10y"] == -0.42


def test_market_sentiment_fails_soft_per_source(monkeypatch):
    import market_intelligence as mi

    def _boom():
        raise RuntimeError("yahoo down")

    monkeypatch.setattr(mi, "get_vix_current", _boom)
    monkeypatch.setattr(mi, "fetch_fear_greed", lambda: {"score": 30.0, "rating": "fear"})
    monkeypatch.setattr(mi, "fetch_yield_curve", _boom)

    out = ct.execute_tool("get_market_sentiment", {})
    data = json.loads(out)
    assert data["vix"] == "unavailable"
    assert data["yield_curve"] == "unavailable"
    assert data["fear_greed"]["rating"] == "fear"  # the one good source survives


# ── execute_tool: macro news ───────────────────────────────────────────


def test_macro_news_truncates_titles(monkeypatch):
    import market_intelligence as mi

    long_title = "A" * 300
    monkeypatch.setattr(
        mi,
        "get_all_macro_news",
        lambda max_items=8: [
            {"source": "Reuters", "title": long_title},
            {"source": "WSJ", "title": "Fed holds rates"},
            {"source": "X", "title": ""},  # dropped (empty)
        ],
    )

    out = ct.execute_tool("get_macro_news", {})
    rows = json.loads(out)
    assert len(rows) == 2  # empty title dropped
    assert rows[0]["source"] == "Reuters"
    assert len(rows[0]["title"]) <= ct._TITLE_MAX_CHARS + 1  # +1 for ellipsis
    assert rows[0]["title"].endswith("…")


def test_macro_news_fails_soft(monkeypatch):
    import market_intelligence as mi

    def _boom(max_items=8):
        raise RuntimeError("rss down")

    monkeypatch.setattr(mi, "get_all_macro_news", _boom)
    out = ct.execute_tool("get_macro_news", {})
    assert "unavailable" in out.lower()


# ── execute_tool: macro indicators ─────────────────────────────────────


class _FakeSeries:
    def __init__(self, sid, label, val, date):
        self.series_id = sid
        self.label = label
        self.latest_value = val
        self.latest_date = date
        self.points = [object()] * 365  # long array we expect to be dropped


def test_macro_indicators_drops_points(monkeypatch):
    from backend.app.services import macro_data as md

    captured = {}

    def _batch(series, *, days=365):
        captured["series"] = list(series)
        return [
            _FakeSeries("DFF", "Fed Funds", 5.333, "2026-05-29"),
            _FakeSeries("DGS10", "10Y", 4.4, "2026-05-29"),
        ]

    monkeypatch.setattr(md, "get_fred_series_batch", _batch)

    out = ct.execute_tool("get_macro_indicators", {})
    rows = json.loads(out)
    assert captured["series"] == ct._DEFAULT_FRED_SERIES
    assert rows[0] == {
        "series_id": "DFF",
        "label": "Fed Funds",
        "latest_value": 5.333,
        "latest_date": "2026-05-29",
    }
    assert "points" not in rows[0]


def test_macro_indicators_subset_input(monkeypatch):
    from backend.app.services import macro_data as md

    captured = {}

    def _batch(series, *, days=365):
        captured["series"] = list(series)
        return [_FakeSeries("CPIAUCSL", "CPI", 310.1, "2026-04-01")]

    monkeypatch.setattr(md, "get_fred_series_batch", _batch)
    ct.execute_tool("get_macro_indicators", {"series": ["cpiaucsl"]})
    assert captured["series"] == ["CPIAUCSL"]  # uppercased


def test_macro_indicators_fails_soft(monkeypatch):
    from backend.app.services import macro_data as md

    def _boom(series, *, days=365):
        raise RuntimeError("fred down")

    monkeypatch.setattr(md, "get_fred_series_batch", _boom)
    out = ct.execute_tool("get_macro_indicators", {})
    assert "unavailable" in out.lower()


# ── execute_tool: fundamentals ─────────────────────────────────────────


def test_ticker_fundamentals_compact(monkeypatch):
    import market_intelligence as mi

    df = pd.DataFrame(
        {
            "P/E (TTM)": [28.4],
            "EPS (TTM)": [6.1],
            "Beta (5Y)": [1.25],
            "Div Yield": [0.005],
            "Market Cap": [3.4e12],  # not in keep-list → dropped
        },
        index=pd.Index(["AAPL"], name="Ticker"),
    )
    monkeypatch.setattr(mi, "fetch_fundamentals", lambda tks: df)

    out = ct.execute_tool("get_ticker_fundamentals", {"ticker": "aapl"})
    data = json.loads(out)
    assert data["ticker"] == "AAPL"
    assert data["P/E (TTM)"] == 28.4
    assert data["Beta (5Y)"] == 1.25
    assert "Market Cap" not in data  # not in keep-list


def test_ticker_fundamentals_empty(monkeypatch):
    import market_intelligence as mi

    monkeypatch.setattr(mi, "fetch_fundamentals", lambda tks: pd.DataFrame())
    out = ct.execute_tool("get_ticker_fundamentals", {"ticker": "ZZZZ"})
    assert "No fundamentals" in out


def test_ticker_fundamentals_bad_ticker():
    out = ct.execute_tool("get_ticker_fundamentals", {"ticker": ""})
    assert "No valid ticker" in out


def test_ticker_fundamentals_fails_soft(monkeypatch):
    import market_intelligence as mi

    def _boom(tks):
        raise RuntimeError("yf down")

    monkeypatch.setattr(mi, "fetch_fundamentals", _boom)
    out = ct.execute_tool("get_ticker_fundamentals", {"ticker": "MSFT"})
    assert "unavailable" in out.lower()


# ── execute_tool: options IV ───────────────────────────────────────────


def test_options_iv_compact(monkeypatch):
    import volatility_scanner as vs

    monkeypatch.setattr(
        vs,
        "_compute_near_atm_iv",
        lambda tk: {
            "ticker": tk,
            "current_iv": 42.123,
            "iv_rank": 71.5,
            "iv_percentile": 88.2,
            "iv_change_1d": -1.234,
        },
    )
    out = ct.execute_tool("get_ticker_options_iv", {"ticker": "tsla"})
    data = json.loads(out)
    assert data["ticker"] == "TSLA"
    assert data["current_iv"] == 42.12
    assert data["iv_rank"] == 71.5
    assert data["iv_change_1d"] == -1.23


def test_options_iv_none(monkeypatch):
    import volatility_scanner as vs

    monkeypatch.setattr(vs, "_compute_near_atm_iv", lambda tk: None)
    out = ct.execute_tool("get_ticker_options_iv", {"ticker": "BND"})
    assert "No listed options" in out


def test_options_iv_fails_soft(monkeypatch):
    import volatility_scanner as vs

    def _boom(tk):
        raise RuntimeError("chain down")

    monkeypatch.setattr(vs, "_compute_near_atm_iv", _boom)
    out = ct.execute_tool("get_ticker_options_iv", {"ticker": "NVDA"})
    assert "unavailable" in out.lower()


# ── dispatcher guards ──────────────────────────────────────────────────


def test_unknown_tool_fails_soft():
    out = ct.execute_tool("not_a_tool", {})
    assert "Unknown tool" in out


def test_none_input_does_not_raise(monkeypatch):
    import market_intelligence as mi

    monkeypatch.setattr(mi, "get_vix_current", lambda: {"current": 12.0})
    monkeypatch.setattr(mi, "fetch_fear_greed", lambda: {"score": 80, "rating": "extreme greed"})
    monkeypatch.setattr(mi, "fetch_yield_curve", lambda: (pd.DataFrame(), {}))
    # tool_input=None must be tolerated
    out = ct.execute_tool("get_market_sentiment", None)
    assert json.loads(out)["vix"]["current"] == 12.0


def test_tool_specs_shape():
    """Every spec is a valid Anthropic tool def with crisp fields."""
    names = {s["name"] for s in ct.TOOL_SPECS}
    assert names == {
        "get_market_sentiment",
        "get_macro_news",
        "get_macro_indicators",
        "get_ticker_fundamentals",
        "get_ticker_options_iv",
    }
    for spec in ct.TOOL_SPECS:
        assert spec["description"] and len(spec["description"]) > 40
        assert spec["input_schema"]["type"] == "object"


# ── llm_client tool-use loop ───────────────────────────────────────────


class _Block:
    """Minimal stand-in for an Anthropic content block."""

    def __init__(self, type, *, text=None, name=None, input=None, id=None):
        self.type = type
        self.text = text
        self.name = name
        self.input = input
        self.id = id


class _Resp:
    def __init__(self, stop_reason, content):
        self.stop_reason = stop_reason
        self.content = content


class _FakeAnthropicClient:
    """Returns a tool_use turn once, then an end_turn text turn."""

    def __init__(self):
        self.calls = []
        self._turn = 0

        class _Messages:
            def create(_self, **kwargs):
                self.calls.append(kwargs)
                if self._turn == 0:
                    self._turn += 1
                    return _Resp(
                        "tool_use",
                        [
                            _Block("text", text="Let me check the market. "),
                            _Block(
                                "tool_use",
                                name="get_market_sentiment",
                                input={},
                                id="toolu_1",
                            ),
                        ],
                    )
                return _Resp("end_turn", [_Block("text", text="Markets look calm.")])

        self.messages = _Messages()


def test_tool_loop_invokes_executor_and_returns_text(monkeypatch):
    from backend.app.services import llm_client as lc

    fake = _FakeAnthropicClient()
    monkeypatch.setattr(lc, "_get_client", lambda: fake)

    invoked = {}

    def _fake_execute(name, tool_input):
        invoked["name"] = name
        return '{"vix":{"current":15}}'

    # The loop imports execute_tool lazily from copilot_tools.
    from backend.app.services import copilot_tools as ctmod

    monkeypatch.setattr(ctmod, "execute_tool", _fake_execute)

    llm = lc.get_llm_callable(with_tools=True)
    assert llm is not None
    out = llm("diagnose risk", "be helpful", 2000, 0.3)

    assert invoked["name"] == "get_market_sentiment"
    assert out == "Markets look calm."
    # Two creates: tool_use turn, then the final end_turn turn.
    assert len(fake.calls) == 2
    # Sonnet + tools were passed on the tool path.
    assert fake.calls[0]["model"] == lc._SONNET_MODEL
    assert "tools" in fake.calls[0]
    # A tool_result was fed back as the second user turn.
    second_user = fake.calls[1]["messages"][-1]
    assert second_user["role"] == "user"
    assert second_user["content"][0]["type"] == "tool_result"
    assert second_user["content"][0]["tool_use_id"] == "toolu_1"


def test_tool_loop_caps_iterations(monkeypatch):
    """A client that NEVER stops asking for tools must terminate at
    MAX_TOOL_TURNS rather than loop forever."""
    from backend.app.services import llm_client as lc

    class _AlwaysToolClient:
        def __init__(self):
            self.n = 0
            self.had_tools = []

            class _M:
                def create(_s, **kwargs):
                    self.n += 1
                    self.had_tools.append("tools" in kwargs)
                    return _Resp(
                        "tool_use",
                        [_Block("tool_use", name="get_macro_news", input={}, id=f"t{self.n}")],
                    )

            self.messages = _M()

    fake = _AlwaysToolClient()
    monkeypatch.setattr(lc, "_get_client", lambda: fake)
    monkeypatch.setattr(
        __import__("backend.app.services.copilot_tools", fromlist=["execute_tool"]),
        "execute_tool",
        lambda name, ti: "ok",
    )

    llm = lc.get_llm_callable(with_tools=True)
    llm("x", "y", 1000, 0.2)
    assert fake.n == lc.MAX_TOOL_TURNS  # capped, no infinite loop
    # The FINAL turn withholds tools so the model must synthesize a text
    # answer instead of being able to request yet another tool.
    assert fake.had_tools == [True] * (lc.MAX_TOOL_TURNS - 1) + [False]


def test_tool_loop_falls_back_to_plain_on_error(monkeypatch):
    """If the tool loop throws, we degrade to a single no-tools create."""
    from backend.app.services import llm_client as lc

    class _ExplodingThenPlainClient:
        def __init__(self):
            self.calls = []

            class _M:
                def create(_s, **kwargs):
                    self.calls.append(kwargs)
                    if "tools" in kwargs:
                        raise RuntimeError("tool loop blew up")
                    return _Resp("end_turn", [_Block("text", text="plain fallback answer")])

            self.messages = _M()

    fake = _ExplodingThenPlainClient()
    monkeypatch.setattr(lc, "_get_client", lambda: fake)

    llm = lc.get_llm_callable(with_tools=True)
    out = llm("x", "y", 2000, 0.2)
    assert out == "plain fallback answer"
    # First create had tools (raised), second was the plain fallback.
    assert "tools" in fake.calls[0]
    assert "tools" not in fake.calls[1]


def test_get_llm_callable_degrades_to_none_without_key(monkeypatch):
    """No client → None, for BOTH the plain and tool paths."""
    from backend.app.services import llm_client as lc

    monkeypatch.setattr(lc, "_get_client", lambda: None)
    assert lc.get_llm_callable() is None
    assert lc.get_llm_callable(with_tools=True) is None


def test_with_tools_default_preserves_plain_path(monkeypatch):
    """Default (with_tools=False) returns the plain Haiku/Sonnet callable —
    keeps existing call sites + tests valid."""
    from backend.app.services import llm_client as lc

    class _PlainClient:
        def __init__(self):
            class _M:
                def create(_s, **kwargs):
                    assert "tools" not in kwargs
                    return _Resp("end_turn", [_Block("text", text="hi")])

            self.messages = _M()

    monkeypatch.setattr(lc, "_get_client", lambda: _PlainClient())
    llm = lc.get_llm_callable()  # default
    assert llm("p", "s", 500, 0.1) == "hi"
