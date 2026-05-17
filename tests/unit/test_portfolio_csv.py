import pytest

from libs.auth.portfolio_csv import parse_holdings_csv


def test_parse_holdings_csv_basic_columns():
    raw = "ticker,shares,avg_cost\nAAPL,10,175.5\nMSFT,2,\n"

    assert parse_holdings_csv(raw) == {
        "AAPL": {"shares": 10.0, "avg_cost": 175.5},
        "MSFT": {"shares": 2.0},
    }


def test_parse_holdings_csv_alias_columns_and_currency():
    raw = 'Symbol,Quantity,Cost Basis\nNVDA,"1,200","$98.25"\n'

    assert parse_holdings_csv(raw) == {"NVDA": {"shares": 1200.0, "avg_cost": 98.25}}


def test_parse_holdings_csv_preserves_sector_metadata():
    raw = "symbol,qty,sector\nIBM,3,Technology / IT Services\n"

    assert parse_holdings_csv(raw) == {"IBM": {"shares": 3.0, "sector": "Technology / IT Services"}}


def test_parse_holdings_csv_combines_duplicate_tickers_weighted_cost():
    raw = "symbol,qty,average_cost\nAAPL,10,100\nAAPL,30,200\n"

    assert parse_holdings_csv(raw) == {"AAPL": {"shares": 40.0, "avg_cost": 175.0}}


def test_parse_holdings_csv_requires_ticker_and_shares():
    with pytest.raises(ValueError, match="ticker/symbol"):
        parse_holdings_csv("name,shares\nApple,10\n")

    with pytest.raises(ValueError, match="shares/quantity"):
        parse_holdings_csv("ticker,value\nAAPL,10\n")


def test_parse_holdings_csv_rejects_oversized_payload():
    huge = ("ticker,shares\n" + "AAPL,1\n" * 200_000).encode()
    with pytest.raises(ValueError, match="too large"):
        parse_holdings_csv(huge)


def test_parse_holdings_csv_rejects_negative_shares():
    with pytest.raises(ValueError, match="negative shares"):
        parse_holdings_csv("ticker,shares\nAAPL,(100)\n")


def test_parse_holdings_csv_rejects_non_finite_shares():
    with pytest.raises(ValueError, match="finite number"):
        parse_holdings_csv("ticker,shares\nAAPL,inf\n")


def test_parse_holdings_csv_rejects_malformed_ticker():
    # Formula-injection / XSS attempt — must be rejected before storage.
    with pytest.raises(ValueError, match="not a recognizable symbol"):
        parse_holdings_csv("ticker,shares\n=cmd|'/c calc'!A0,10\n")


def test_parse_holdings_csv_accepts_class_share_and_crypto():
    parsed = parse_holdings_csv("ticker,shares\nBRK.B,3\nBTC-USD,0.1\n")
    assert set(parsed.keys()) == {"BRK.B", "BTC-USD"}


# ── parse_holdings_csv_with_diagnostics — per-row tolerant ────────────


def test_diagnostics_returns_valid_and_errors_split():
    from libs.auth.portfolio_csv import parse_holdings_csv_with_diagnostics

    csv = (
        "ticker,shares,avg_cost\n"
        "AAPL,10,175\n"
        "=cmd|'/c calc'!A0,5,\n"  # malformed ticker
        "MSFT,(-3),200\n"  # negative shares
        "NVDA,nan,\n"  # non-finite shares
        "GOOG,5,99\n"
        ",,,\n"  # blank ticker, skipped silently
    )
    result = parse_holdings_csv_with_diagnostics(csv)
    assert set(result["valid"].keys()) == {"AAPL", "GOOG"}
    assert len(result["errors"]) == 3
    error_rows = sorted(e["row"] for e in result["errors"])
    assert error_rows == [3, 4, 5]
    # Skipped count includes the blank-ticker row.
    assert result["skipped"] >= 1


def test_diagnostics_keeps_partial_when_only_avg_cost_is_bad():
    from libs.auth.portfolio_csv import parse_holdings_csv_with_diagnostics

    csv = "ticker,shares,avg_cost\nAAPL,10,not_a_number\nMSFT,5,200\n"
    result = parse_holdings_csv_with_diagnostics(csv)
    # AAPL kept (shares still valid) but flagged in errors as cost dropped.
    assert "AAPL" in result["valid"]
    assert "avg_cost" not in result["valid"]["AAPL"]
    assert any(e["ticker"] == "AAPL" and "cost dropped" in e["reason"] for e in result["errors"])
    assert result["valid"]["MSFT"]["avg_cost"] == 200.0


def test_diagnostics_still_rejects_oversized_file():
    """Structural problems are unrecoverable — still raise."""
    from libs.auth.portfolio_csv import parse_holdings_csv_with_diagnostics

    huge = ("ticker,shares\n" + "AAPL,1\n" * 200_000).encode()
    with pytest.raises(ValueError, match="too large"):
        parse_holdings_csv_with_diagnostics(huge)


def test_diagnostics_still_rejects_missing_required_columns():
    from libs.auth.portfolio_csv import parse_holdings_csv_with_diagnostics

    with pytest.raises(ValueError, match="missing required"):
        parse_holdings_csv_with_diagnostics("name,price\nApple,175\n")
