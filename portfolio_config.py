"""
portfolio_config.py — Single source of truth for portfolio state.

Three top-level entities:
  1. PORTFOLIO_HOLDINGS   : per-ticker positions (shares + optional metadata)
  2. ACCOUNTS             : broker / wallet accounts with per-account margin loan
  3. CONTRIBUTED_CAPITAL  : total self-funded principal (excludes margin draws)

Backward compat aliases:
  - TOTAL_COST_BASIS  == CONTRIBUTED_CAPITAL
  - MARGIN_LOAN       == sum of ACCOUNTS[*]["margin_loan"] (scalar rollup)

Position metadata is optional — minimum requirement is `shares`. Call
`get_holding(ticker)` to receive a dict with defaults filled in
(account='default', currency='USD', asset_type inferred from ticker, etc).

Run `validate_portfolio_config()` at app start for a list of issues.
"""

from typing import Dict, List, Any


# ══════════════════════════════════════════════════════════════════════════════
#  Positions
# ══════════════════════════════════════════════════════════════════════════════
# Optional keys per holding:
#   shares           (required)
#   avg_cost         price/share used for position P&L; None = unknown
#   account          key into ACCOUNTS; default "margin"
#   asset_type       "equity" | "etf" | "inverse_etf" | "crypto" | "option" | "cash"
#                    inferred from ticker suffix if omitted
#   currency         default "USD"
#   margin_eligible  default True for equity/etf, False for crypto/inverse_etf

PORTFOLIO_HOLDINGS: Dict[str, Dict[str, Any]] = {
    # Equities — margin account
    'NVDA':  {'shares': 25.00,  'account': 'margin', 'asset_type': 'equity'},
    'GOOGL': {'shares': 12.41,  'account': 'margin', 'asset_type': 'equity'},
    'META':  {'shares': 6.46,   'account': 'margin', 'asset_type': 'equity'},
    'MSFT':  {'shares': 9.19,   'account': 'margin', 'asset_type': 'equity'},
    'TSLA':  {'shares': 9.00,   'account': 'margin', 'asset_type': 'equity'},
    'TSM':   {'shares': 5.39,   'account': 'margin', 'asset_type': 'equity'},
    'NFLX':  {'shares': 17.01,  'account': 'margin', 'asset_type': 'equity'},
    'AVGO':  {'shares': 4.02,   'account': 'margin', 'asset_type': 'equity'},
    'AXP':   {'shares': 5.00,   'account': 'margin', 'asset_type': 'equity'},
    'INTU':  {'shares': 3.00,   'account': 'margin', 'asset_type': 'equity'},
    'MU':    {'shares': 0.77,   'account': 'margin', 'asset_type': 'equity'},
    'SOFI':  {'shares': 45.00,  'account': 'margin', 'asset_type': 'equity'},
    'VST':   {'shares': 4.01,   'account': 'margin', 'asset_type': 'equity'},
    'COST':  {'shares': 0.55,   'account': 'margin', 'asset_type': 'equity'},
    'HOOD':  {'shares': 10.00,  'account': 'margin', 'asset_type': 'equity'},
    'ONDS':  {'shares': 30.00,  'account': 'margin', 'asset_type': 'equity'},
    'COPX':  {'shares': 5.00,   'account': 'margin', 'asset_type': 'etf'},
    'AA':    {'shares': 7.01,   'account': 'margin', 'asset_type': 'equity'},
    'QQQ':   {'shares': 2.24,   'account': 'margin', 'asset_type': 'etf'},
    'SPY':   {'shares': 2.03,   'account': 'margin', 'asset_type': 'etf'},
    'GLD':   {'shares': 2.53,   'account': 'margin', 'asset_type': 'etf'},
    # Inverse leveraged ETFs — hedging instruments, NOT margin eligible
    'SQQQ':  {'shares': 13.00,  'account': 'margin', 'asset_type': 'inverse_etf', 'margin_eligible': False},
    'SOXS':  {'shares': 10.00,  'account': 'margin', 'asset_type': 'inverse_etf', 'margin_eligible': False},
    'SPXS':  {'shares': 5.00,   'account': 'margin', 'asset_type': 'inverse_etf', 'margin_eligible': False},

    # Crypto — separate wallet, never margin
    'BTC-USD':  {'shares': 0.038, 'account': 'crypto', 'asset_type': 'crypto', 'margin_eligible': False},
    'ETH-USD':  {'shares': 0.60,  'account': 'crypto', 'asset_type': 'crypto', 'margin_eligible': False},
    'XRP-USD':  {'shares': 236,   'account': 'crypto', 'asset_type': 'crypto', 'margin_eligible': False},
    'ADA-USD':  {'shares': 1133,  'account': 'crypto', 'asset_type': 'crypto', 'margin_eligible': False},
    'SOL-USD':  {'shares': 2.5,   'account': 'crypto', 'asset_type': 'crypto', 'margin_eligible': False},
    'LINK-USD': {'shares': 16.00, 'account': 'crypto', 'asset_type': 'crypto', 'margin_eligible': False},
}


# ══════════════════════════════════════════════════════════════════════════════
#  Accounts
# ══════════════════════════════════════════════════════════════════════════════
ACCOUNTS: Dict[str, Dict[str, Any]] = {
    'margin': {
        'type': 'margin',
        'broker': 'default_broker',
        'margin_loan': 16822,
        'maintenance_req': 0.25,
        'base_currency': 'USD',
    },
    'crypto': {
        'type': 'crypto_wallet',
        'broker': 'default_crypto',
        'margin_loan': 0,
        'base_currency': 'USD',
    },
}

# ══════════════════════════════════════════════════════════════════════════════
#  Capital
# ══════════════════════════════════════════════════════════════════════════════
# Self-funded principal — money YOU put in, excludes margin draws.
# Used to compute "Return on Contributed Capital" (how well your own money did).
CONTRIBUTED_CAPITAL = 19700

# ── Backward-compat aliases (legacy callers) ─────────────────────────────────
TOTAL_COST_BASIS = CONTRIBUTED_CAPITAL
MARGIN_LOAN = sum(a.get('margin_loan', 0) for a in ACCOUNTS.values())


# ══════════════════════════════════════════════════════════════════════════════
#  Sector classification — single source, downstream falls back to "Other"
# ══════════════════════════════════════════════════════════════════════════════
SECTOR_MAP: Dict[str, str] = {
    "NVDA": "Semiconductors", "AVGO": "Semiconductors", "TSM": "Semiconductors",
    "MU": "Semiconductors", "INTC": "Semiconductors", "AMD": "Semiconductors",
    "QCOM": "Semiconductors", "TXN": "Semiconductors",
    "GOOGL": "Big Tech", "GOOG": "Big Tech", "MSFT": "Big Tech",
    "META": "Big Tech", "AAPL": "Big Tech", "AMZN": "Big Tech",
    "INTU": "Software", "CRM": "Software", "SNOW": "Software", "NOW": "Software",
    "TSLA": "EV / Auto", "CPNG": "E-commerce", "BABA": "E-commerce",
    "NFLX": "Streaming / Media", "DIS": "Streaming / Media",
    "AXP": "Financials", "JPM": "Financials", "GS": "Financials",
    "SOFI": "Fintech", "HOOD": "Fintech", "PYPL": "Fintech", "SQ": "Fintech",
    "S": "Cybersecurity", "CRWD": "Cybersecurity", "PANW": "Cybersecurity",
    "SMMT": "Biotech", "ONDS": "Technology / IoT",
    "AA": "Materials", "COPX": "Mining ETF", "VST": "Utilities",
    "COST": "Consumer Staples", "WMT": "Consumer Staples",
    "TQQQ": "Leveraged ETF", "QQQ": "Tech ETF",
    "SPY": "Broad Market ETF", "GLD": "Gold / Commodities", "SLV": "Gold / Commodities",
    "SQQQ": "Inverse ETF (3x QQQ)",
    "SOXS": "Inverse ETF (3x Semis)",
    "SPXS": "Inverse ETF (3x S&P)",
    "BTC-USD": "Crypto", "ETH-USD": "Crypto", "XRP-USD": "Crypto",
    "ADA-USD": "Crypto", "SOL-USD": "Crypto", "LINK-USD": "Crypto",
    "DOGE-USD": "Crypto", "BNB-USD": "Crypto",
}


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _infer_asset_type(ticker: str) -> str:
    if ticker.upper().endswith("-USD"):
        return "crypto"
    if ticker.upper() in {"SQQQ", "SOXS", "SPXS", "SDS", "PSQ"}:
        return "inverse_etf"
    if ticker.upper() in {"SPY", "QQQ", "TQQQ", "GLD", "SLV", "IWM", "TLT", "VTV", "COPX"}:
        return "etf"
    return "equity"


def get_holding(ticker: str) -> Dict[str, Any]:
    """
    Return the full holding record with defaults filled in.
    Missing fields are inferred from the ticker symbol.
    """
    h = PORTFOLIO_HOLDINGS.get(ticker, {})
    asset_type = h.get("asset_type") or _infer_asset_type(ticker)
    is_crypto = asset_type == "crypto"
    is_inverse = asset_type == "inverse_etf"
    return {
        "shares": float(h.get("shares", 0.0)),
        "avg_cost": h.get("avg_cost"),
        "account": h.get("account", "crypto" if is_crypto else "margin"),
        "asset_type": asset_type,
        "currency": h.get("currency", "USD"),
        "margin_eligible": h.get("margin_eligible", not (is_crypto or is_inverse)),
    }


def position_cost_summary() -> Dict[str, Any]:
    """
    Aggregate per-position cost (shares * avg_cost) across tickers that have
    `avg_cost` set. Tickers without avg_cost are listed separately so the UI
    can tell the user which need backfilling for real P&L.
    """
    total = 0.0
    known, unknown = [], []
    for tk, h in PORTFOLIO_HOLDINGS.items():
        avg = h.get("avg_cost")
        shares = h.get("shares", 0)
        if avg is not None and avg > 0 and shares > 0:
            total += float(shares) * float(avg)
            known.append(tk)
        else:
            unknown.append(tk)
    return {
        "total_position_cost": total,
        "tickers_with_cost": known,
        "tickers_missing_cost": unknown,
        "coverage_pct": len(known) / max(len(PORTFOLIO_HOLDINGS), 1),
    }


def account_summary(account_name: str, market_values: Dict[str, float]) -> Dict[str, Any]:
    """
    Aggregate total long / net equity / leverage for ONE account, using
    the provided ticker -> market-value dict (typically computed from
    live prices * shares by the caller).
    """
    acct = ACCOUNTS.get(account_name, {})
    total_long = 0.0
    for tk, h in PORTFOLIO_HOLDINGS.items():
        if get_holding(tk)["account"] != account_name:
            continue
        total_long += float(market_values.get(tk, 0.0))
    loan = float(acct.get("margin_loan", 0))
    net_equity = total_long - loan
    return {
        "account": account_name,
        "type": acct.get("type", "unknown"),
        "total_long": total_long,
        "margin_loan": loan,
        "net_equity": net_equity,
        "leverage": (total_long / net_equity) if net_equity > 0 else float("inf"),
    }


def validate_portfolio_config() -> List[str]:
    """
    Startup sanity-check. Returns a list of human-readable issues.
    Callers should display warnings but not crash — missing metadata is
    recoverable via `get_holding()` defaults.
    """
    issues: List[str] = []

    # Per-holding checks
    for tk, h in PORTFOLIO_HOLDINGS.items():
        if not isinstance(tk, str) or not tk.strip():
            issues.append(f"invalid ticker symbol: {tk!r}")
            continue

        shares = h.get("shares")
        if shares is None or shares <= 0:
            issues.append(f"{tk}: shares must be > 0 (got {shares!r})")

        if tk not in SECTOR_MAP:
            issues.append(
                f"{tk}: missing from SECTOR_MAP — will show as 'Other' and "
                f"escape sector-concentration limits"
            )

        # Crypto tickers should use the `-USD` suffix convention
        if h.get("asset_type") == "crypto" and not tk.upper().endswith("-USD"):
            issues.append(f"{tk}: asset_type=crypto but ticker doesn't end with -USD")

        # Account must exist if specified
        acct = h.get("account")
        if acct is not None and acct not in ACCOUNTS:
            issues.append(f"{tk}: account '{acct}' not defined in ACCOUNTS")

        # avg_cost sanity
        avg = h.get("avg_cost")
        if avg is not None and (not isinstance(avg, (int, float)) or avg <= 0):
            issues.append(f"{tk}: avg_cost must be a positive number (got {avg!r})")

    # Cross-check accounts
    for name, acct in ACCOUNTS.items():
        loan = acct.get("margin_loan", 0)
        if loan < 0:
            issues.append(f"account '{name}': margin_loan must be >= 0 (got {loan})")

    # Contributed capital sanity
    if CONTRIBUTED_CAPITAL < 0:
        issues.append(f"CONTRIBUTED_CAPITAL must be >= 0 (got {CONTRIBUTED_CAPITAL})")

    return issues
