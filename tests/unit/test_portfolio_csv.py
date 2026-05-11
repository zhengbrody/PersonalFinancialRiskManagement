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
