"""
institutional_tracker.py
SEC 13F Institutional Holdings Tracker v1.0
──────────────────────────────────────────────────────────
Fetches and analyzes 13F filings from SEC EDGAR to track
institutional holdings by top hedge funds and asset managers.

Features:
  1. Top ~30 most-watched institutional filers (CIK registry)
  2. 13F filing fetch & parse via SEC EDGAR API
  3. Per-ticker institutional ownership cross-reference
  4. Smart money signals for portfolio holdings
  5. Quarter-over-quarter position change detection

SEC EDGAR compliance:
  - User-Agent header: "MindMarket AI research@mindmarket.ai"
  - Rate limit: max 10 requests/second
  - Results cached for 24 hours (filings change quarterly)

Dependencies: requests, yfinance (all in requirements.txt)
"""

import hashlib
import json
import os
import time
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

import requests

from logging_config import get_logger

logger = get_logger(__name__)

# ══════════════════════════════════════════════════════════════
#  Constants
# ══════════════════════════════════════════════════════════════

CACHE_DIR = ".cache/institutional_tracker"
CACHE_MAX_AGE_SECONDS = 86400  # 24 hours — filings only change quarterly

SEC_BASE_URL = "https://data.sec.gov"
SEC_ARCHIVES_URL = "https://www.sec.gov"
SEC_EFTS_URL = "https://efts.sec.gov/LATEST"
SEC_HEADERS = {
    "User-Agent": "MindMarket AI research@mindmarket.ai",
    "Accept-Encoding": "gzip, deflate",
}

# Rate limiter: SEC allows max 10 req/sec
_last_request_time = 0.0
_MIN_REQUEST_INTERVAL = 0.12  # ~8 req/sec to stay safely under limit


# ══════════════════════════════════════════════════════════════
#  CUSIP-to-Ticker Mapping (top ~200 stocks)
# ══════════════════════════════════════════════════════════════

CUSIP_TO_TICKER = {
    # Mega-cap tech
    "037833100": "AAPL",  # Apple
    "594918104": "MSFT",  # Microsoft
    "67066G104": "NVDA",  # NVIDIA
    "02079K305": "GOOGL",  # Alphabet Class A
    "02079K107": "GOOG",  # Alphabet Class C
    "023135106": "AMZN",  # Amazon
    "30303M102": "META",  # Meta Platforms
    "88160R101": "TSLA",  # Tesla
    "084670702": "BRK-B",  # Berkshire Hathaway B
    "084670108": "BRK-A",  # Berkshire Hathaway A
    # Semiconductors
    "11135F101": "AVGO",  # Broadcom
    "007903107": "AMD",  # AMD
    "458140100": "INTC",  # Intel
    "874568002": "TXN",  # Texas Instruments
    "868857108": "QCOM",  # Qualcomm
    "00507V109": "AMAT",  # Applied Materials
    "512807108": "LRCX",  # Lam Research
    "482480100": "KLAC",  # KLA Corp
    "03662Q105": "ARM",  # ARM Holdings
    # Software / Cloud
    "79466L302": "CRM",  # Salesforce
    "00724F101": "ADBE",  # Adobe
    "668771300": "NOW",  # ServiceNow
    "44107P104": "INTU",  # Intuit
    "72352L106": "PANW",  # Palo Alto Networks
    "22788C105": "CRWD",  # CrowdStrike
    "34959E109": "FTNT",  # Fortinet
    "69608A108": "PLTR",  # Palantir
    "68389X105": "ORCL",  # Oracle
    # Financials
    "46625H100": "JPM",  # JPMorgan Chase
    "060505104": "BAC",  # Bank of America
    "92826C839": "V",  # Visa
    "57636Q104": "MA",  # Mastercard
    "172967424": "C",  # Citigroup
    "808513105": "SCHW",  # Charles Schwab
    "38141G104": "GS",  # Goldman Sachs
    "617446448": "MS",  # Morgan Stanley
    "902973304": "USB",  # US Bancorp
    "09247X101": "BLK",  # BlackRock
    # Healthcare
    "91324P102": "UNH",  # UnitedHealth
    "049560105": "LLY",  # Eli Lilly
    "478160104": "JNJ",  # Johnson & Johnson
    "58933Y105": "MRK",  # Merck
    "00287Y109": "ABBV",  # AbbVie
    "717081103": "PFE",  # Pfizer
    "110122108": "BMY",  # Bristol-Myers Squibb
    "88322Q108": "TMO",  # Thermo Fisher
    "002824100": "ABT",  # Abbott Labs
    "863667101": "SYK",  # Stryker
    "46120E602": "ISRG",  # Intuitive Surgical
    "375558103": "GILD",  # Gilead Sciences
    "543370108": "REGN",  # Regeneron
    "92532F100": "VRTX",  # Vertex Pharma
    "00846U101": "AMGN",  # Amgen
    # Consumer
    "22160K105": "COST",  # Costco
    "437076102": "HD",  # Home Depot
    "931142103": "WMT",  # Walmart
    "64110L106": "NFLX",  # Netflix
    "548661107": "LOW",  # Lowe's
    "580135101": "MCD",  # McDonald's
    "191216100": "KO",  # Coca-Cola
    "713448108": "PEP",  # PepsiCo
    "742718109": "PG",  # Procter & Gamble
    "17275R102": "CSCO",  # Cisco
    "00971T101": "BKNG",  # Booking Holdings
    "609207105": "MDLZ",  # Mondelez
    "172062101": "CL",  # Colgate-Palmolive
    "609207950": "MO",  # Altria (Philip Morris parent)
    "718172109": "PM",  # Philip Morris Intl
    "90384S303": "UBER",  # Uber
    "15223T107": "ABNB",  # Airbnb
    "25809K105": "DASH",  # DoorDash
    # Energy
    "30231G102": "XOM",  # Exxon Mobil
    "166764100": "CVX",  # Chevron
    "26875P101": "EOG",  # EOG Resources
    "806857108": "SLB",  # Schlumberger
    # Industrials
    "907818108": "UNP",  # Union Pacific
    "75513E101": "RTX",  # RTX (Raytheon)
    "438516106": "HON",  # Honeywell
    "369604103": "GE",  # GE Aerospace
    "244199105": "DE",  # Deere
    "002546108": "ACN",  # Accenture
    "053015103": "ADP",  # ADP
    "236521105": "DHR",  # Danaher
    "269246401": "FDX",  # FedEx
    "961214209": "WM",  # Waste Management
    # Utilities / REITs
    "65339F101": "NEE",  # NextEra Energy
    "842587107": "SO",  # Southern Co
    "263534109": "DUK",  # Duke Energy
    "743315103": "PGR",  # Progressive Corp
    "73278L105": "PLD",  # Prologis
    # Other notable
    "552953101": "CME",  # CME Group
    # 458140100 is Intel (line 75), not ICE — keeping INTC mapping
    "571903202": "MMC",  # Marsh McLennan
    "125523100": "CI",  # Cigna
    # 00287Y109 is AbbVie (line 108), not ELV — keeping ABBV mapping
    "98978V103": "ZTS",  # Zoetis
    "70450Y103": "PYPL",  # PayPal
    "00206R102": "T",  # AT&T
    "92343V104": "VZ",  # Verizon
    "22822V101": "CRWD",  # CrowdStrike (alt CUSIP)
    "00790R104": "ADI",  # Analog Devices
    "86800U104": "SNPS",  # Synopsys
    "12673P105": "CDNS",  # Cadence
    "003654108": "APD",  # Air Products
    "589331107": "MCK",  # McKesson
    "00108J109": "AJG",  # Arthur J Gallagher
    "1326801": "COIN",  # Coinbase (newer listing)
    "584404107": "MELI",  # MercadoLibre
    # ARK-held names (TSLA, JPM, VZ already mapped above)
    "862121100": "SQ",  # Block (Square)
    "64110W142": "NFLX",  # alt CUSIP
    "78468R107": "ROKU",  # Roku
    "09857L108": "BIDU",  # Baidu
    "98980L101": "ZM",  # Zoom
    "58463J304": "MELI",  # alt CUSIP
    "74587V107": "QCOM",  # alt CUSIP
}

# Reverse lookup: ticker -> list of CUSIPs (for ownership search)
TICKER_TO_CUSIPS: Dict[str, List[str]] = {}
for _cusip, _tkr in CUSIP_TO_TICKER.items():
    TICKER_TO_CUSIPS.setdefault(_tkr, []).append(_cusip)


# ══════════════════════════════════════════════════════════════
#  Section 1 — Top Institutional Filers Registry
# ══════════════════════════════════════════════════════════════

# CIK numbers sourced from SEC EDGAR full-text search
# Format: (display_name, CIK as zero-padded 10-digit string)
_TOP_INSTITUTIONS = [
    # Legendary value / macro
    ("Berkshire Hathaway", "0001067983"),
    ("Bridgewater Associates", "0001350694"),
    ("Renaissance Technologies", "0001037389"),
    # Multi-strategy hedge funds
    ("Citadel Advisors", "0001423053"),
    ("Point72 Asset Management", "0001603466"),
    ("Millennium Management", "0001273087"),
    ("DE Shaw & Co", "0001009207"),
    ("Two Sigma Investments", "0001179392"),
    # Tiger cubs / activist
    ("Tiger Global Management", "0001167483"),
    ("Appaloosa Management", "0001656456"),
    ("Baupost Group", "0001061768"),
    ("Pershing Square Capital", "0001336528"),
    ("Third Point", "0001040273"),
    ("Icahn Enterprises", "0000049588"),
    ("Soros Fund Management", "0001029160"),
    ("Greenlight Capital", "0001079114"),
    # Quant / systematic
    ("AQR Capital Management", "0001167557"),
    ("Lone Pine Capital", "0001061165"),
    ("Viking Global Investors", "0001103804"),
    ("Coatue Management", "0001535392"),
    ("Dragoneer Investment", "0001571983"),
    # Thematic / ETF
    ("ARK Investment Management", "0001697748"),
    # Mega asset managers
    ("BlackRock", "0001364742"),
    ("Vanguard Group", "0000102909"),
    ("State Street Corporation", "0000093751"),
    ("Fidelity (FMR LLC)", "0000315066"),
    # Investment banks
    ("JPMorgan Chase & Co", "0000019617"),
    ("Goldman Sachs Group", "0000886982"),
    ("Morgan Stanley", "0000895421"),
    # Mutual fund giants
    ("T. Rowe Price Associates", "0001549575"),
    ("Capital Group Companies", "0000783412"),
]


def get_top_institutions() -> List[Dict[str, str]]:
    """
    Return the top ~30 most-watched institutional 13F filers.

    Returns
    -------
    list[dict]
        Each dict has keys: 'name' (str), 'cik' (str, zero-padded 10 digits).

    Example
    -------
    >>> insts = get_top_institutions()
    >>> insts[0]
    {'name': 'Berkshire Hathaway', 'cik': '0001067983'}
    """
    return [{"name": name, "cik": cik} for name, cik in _TOP_INSTITUTIONS]


# ══════════════════════════════════════════════════════════════
#  File-based Cache
# ══════════════════════════════════════════════════════════════


def _ensure_cache_dir():
    """Create cache directory if it does not exist."""
    os.makedirs(CACHE_DIR, exist_ok=True)


def _cache_key(func_name: str, args_repr: str) -> str:
    """Produce a deterministic filename-safe cache key."""
    raw = f"{func_name}:{args_repr}"
    h = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"{func_name}_{h}.json"


def _read_cache(key: str) -> Optional[dict]:
    """Read from JSON cache if not expired. Returns None on miss."""
    _ensure_cache_dir()
    path = os.path.join(CACHE_DIR, key)
    if not os.path.exists(path):
        return None
    try:
        mtime = os.path.getmtime(path)
        age = time.time() - mtime
        if age > CACHE_MAX_AGE_SECONDS:
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("cache_read_error", key=key, error=str(exc))
        return None


def _write_cache(key: str, data) -> None:
    """Write data to JSON cache."""
    _ensure_cache_dir()
    path = os.path.join(CACHE_DIR, key)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
    except Exception as exc:
        logger.warning("cache_write_error", key=key, error=str(exc))


# ══════════════════════════════════════════════════════════════
#  SEC EDGAR Rate-Limited Request
# ══════════════════════════════════════════════════════════════


def _sec_get(url: str, timeout: int = 15) -> Optional[requests.Response]:
    """
    Rate-limited GET request to SEC EDGAR.

    Enforces a minimum interval between requests to stay under the
    SEC's 10 requests/second limit. Returns None on failure.
    """
    global _last_request_time

    # Rate limit enforcement
    now = time.time()
    elapsed = now - _last_request_time
    if elapsed < _MIN_REQUEST_INTERVAL:
        time.sleep(_MIN_REQUEST_INTERVAL - elapsed)

    try:
        resp = requests.get(url, headers=SEC_HEADERS, timeout=timeout)
        _last_request_time = time.time()

        if resp.status_code == 200:
            return resp
        elif resp.status_code == 429:
            logger.warning("sec_rate_limited", url=url)
            time.sleep(2.0)
            # One retry after rate limit
            resp = requests.get(url, headers=SEC_HEADERS, timeout=timeout)
            _last_request_time = time.time()
            if resp.status_code == 200:
                return resp
        else:
            logger.warning(
                "sec_request_failed",
                url=url,
                status_code=resp.status_code,
            )
    except requests.exceptions.Timeout:
        logger.warning("sec_request_timeout", url=url)
    except requests.exceptions.RequestException as exc:
        logger.error("sec_request_error", url=url, error=str(exc))

    return None


# ══════════════════════════════════════════════════════════════
#  CUSIP / Ticker Resolution
# ══════════════════════════════════════════════════════════════

_yfinance_cusip_cache: Dict[str, str] = {}


def _cusip_to_ticker(cusip: str) -> str:
    """
    Resolve a CUSIP to a ticker symbol.

    Priority:
      1. Hardcoded CUSIP_TO_TICKER mapping (~200 common stocks)
      2. Cached yfinance lookups from prior calls
      3. Return the CUSIP itself as a fallback placeholder
    """
    # Strip trailing check digit if 9-char
    cusip_base = cusip[:8] if len(cusip) >= 9 else cusip

    # Check both 8-char and 9-char variants in our mapping
    for variant in [
        cusip,
        cusip_base,
        cusip + "0",
        cusip_base + "0",
        cusip_base + "1",
        cusip_base + "2",
        cusip_base + "3",
    ]:
        if variant in CUSIP_TO_TICKER:
            return CUSIP_TO_TICKER[variant]

    # Check yfinance cache
    if cusip in _yfinance_cusip_cache:
        return _yfinance_cusip_cache[cusip]

    # Return CUSIP as fallback — do not block on yfinance lookup here
    # (caller can enrich later if needed)
    return cusip


def _resolve_cusips_batch(cusips: List[str]) -> Dict[str, str]:
    """
    Attempt to resolve unknown CUSIPs to tickers via yfinance.

    Only looks up CUSIPs not already in the hardcoded mapping.
    Returns a mapping of CUSIP -> ticker for newly resolved entries.
    """
    unknown = [c for c in cusips if _cusip_to_ticker(c) == c]
    if not unknown:
        return {}

    resolved = {}
    try:
        import yfinance as yf

        for cusip in unknown[:50]:  # Limit batch size
            try:
                # yfinance doesn't support CUSIP lookup directly,
                # but we can try searching
                ticker_obj = yf.Ticker(cusip)
                info = ticker_obj.info
                symbol = info.get("symbol")
                if symbol and symbol != cusip:
                    resolved[cusip] = symbol
                    _yfinance_cusip_cache[cusip] = symbol
            except Exception:
                continue
    except ImportError:
        logger.warning("yfinance_not_available", msg="Cannot resolve unknown CUSIPs")

    return resolved


# ══════════════════════════════════════════════════════════════
#  Section 2 — Fetch 13F Holdings from SEC EDGAR
# ══════════════════════════════════════════════════════════════


def _get_filing_urls(cik: str, form_type: str = "13F-HR", limit: int = 2) -> List[Dict]:
    """
    Retrieve the most recent 13F filing URLs for a given CIK.

    Uses SEC EDGAR submissions JSON endpoint:
      https://data.sec.gov/submissions/CIK{cik}.json

    Parameters
    ----------
    cik : str
        CIK number (zero-padded to 10 digits).
    form_type : str
        Filing form type to filter (default: '13F-HR').
    limit : int
        Maximum number of filings to return.

    Returns
    -------
    list[dict]
        Each dict: {accession_number, filing_date, primary_document, form}
    """
    # Ensure CIK is zero-padded to 10 digits
    cik_padded = cik.lstrip("0").zfill(10)
    url = f"{SEC_BASE_URL}/submissions/CIK{cik_padded}.json"

    resp = _sec_get(url)
    if resp is None:
        return []

    try:
        data = resp.json()
    except (json.JSONDecodeError, ValueError):
        logger.error("sec_json_parse_error", url=url)
        return []

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    filing_dates = recent.get("filingDate", [])
    primary_docs = recent.get("primaryDocument", [])

    results = []
    for i, form in enumerate(forms):
        # Match 13F-HR and 13F-HR/A (amendments)
        if form.startswith(form_type) and len(results) < limit:
            acc = accessions[i].replace("-", "")
            acc_dashed = accessions[i]
            results.append(
                {
                    "accession_number": acc_dashed,
                    "filing_date": filing_dates[i],
                    "primary_document": primary_docs[i] if i < len(primary_docs) else "",
                    "form": form,
                    "cik": cik_padded,
                    "archive_url": (
                        f"{SEC_ARCHIVES_URL}/Archives/edgar/data/" f"{cik_padded.lstrip('0')}/{acc}"
                    ),
                }
            )

    return results


def _parse_13f_xml(xml_text: str) -> List[Dict]:
    """
    Parse a 13F information table XML document into a list of holdings.

    Handles both the modern (2013+) XML namespace format and older formats.

    Returns
    -------
    list[dict]
        Each dict: {cusip, name, shares, value, investment_discretion, voting_authority}
    """
    holdings = []

    # Try to parse XML with common 13F namespaces
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        # Try stripping encoding declaration that sometimes causes issues
        cleaned = xml_text
        if cleaned.startswith("<?"):
            idx = cleaned.find("?>")
            if idx > 0:
                cleaned = cleaned[idx + 2 :]
        try:
            root = ET.fromstring(cleaned)
        except ET.ParseError as exc:
            logger.warning("xml_parse_error", error=str(exc))
            return holdings

    # 13F namespace variants — SEC has used several over the years
    _13F_NS_URIS = [
        "http://www.sec.gov/edgar/document/thirteenf/informationtable",
        "http://www.sec.gov/edgar/thirteenffiling",
    ]

    namespaces = {
        "ns": _13F_NS_URIS[0],
        "ns2": "http://www.sec.gov/edgar/common",
    }

    # Auto-detect namespace from the root element
    root_tag = root.tag
    if root_tag.startswith("{"):
        detected_ns = root_tag.split("}")[0].lstrip("{")
        if detected_ns not in _13F_NS_URIS:
            _13F_NS_URIS.append(detected_ns)
        namespaces["ns"] = detected_ns

    # Try each known namespace to find infoTable elements
    info_tables = []
    for ns_uri in _13F_NS_URIS:
        info_tables = root.findall(f".//{{{ns_uri}}}infoTable")
        if info_tables:
            # Update namespaces dict to use the matching URI for extraction
            namespaces["ns"] = ns_uri
            break

    if not info_tables:
        # Try bare element names (very old filings or no namespace)
        info_tables = root.findall(".//infoTable")
    if not info_tables:
        # Last resort: find any element that looks like an entry
        info_tables = root.findall(".//*[cusip]") or root.findall(".//*[CUSIP]")
    if not info_tables:
        # Try case-insensitive search by iterating all elements
        for el in root.iter():
            local = el.tag.split("}")[-1] if "}" in el.tag else el.tag
            if local.lower() == "infotable":
                info_tables.append(el)
                # Detect namespace from this element for extraction
                if "}" in el.tag:
                    ns_uri = el.tag.split("}")[0].lstrip("{")
                    namespaces["ns"] = ns_uri

    for entry in info_tables:
        holding = _extract_holding_from_element(entry, namespaces)
        if holding:
            holdings.append(holding)

    return holdings


def _extract_holding_from_element(entry: ET.Element, namespaces: dict) -> Optional[Dict]:
    """Extract a single holding record from an XML infoTable element."""
    # Resolve the active namespace URI from the namespaces dict
    _active_ns = namespaces.get("ns", "")

    def _find_text(element, tag_variants):
        """Try multiple tag names / namespace combos to find element text."""
        for tag in tag_variants:
            # Try with namespace prefix (uses namespaces dict)
            el = element.find(f"ns:{tag}", namespaces)
            if el is not None and el.text:
                return el.text.strip()
            # Try with the active namespace URI directly
            if _active_ns:
                el = element.find(f"{{{_active_ns}}}{tag}")
                if el is not None and el.text:
                    return el.text.strip()
            # Try bare (no namespace)
            el = element.find(tag)
            if el is not None and el.text:
                return el.text.strip()
        return None

    def _find_element(element, tag_variants):
        """Try multiple tag names / namespace combos to find a child element."""
        for tag in tag_variants:
            el = element.find(f"ns:{tag}", namespaces)
            if el is not None:
                return el
            if _active_ns:
                el = element.find(f"{{{_active_ns}}}{tag}")
                if el is not None:
                    return el
            el = element.find(tag)
            if el is not None:
                return el
        return None

    cusip = _find_text(entry, ["cusip", "CUSIP"])
    if not cusip:
        return None

    name = _find_text(entry, ["nameOfIssuer", "NAMEOFISSUER", "issuerName"]) or "UNKNOWN"

    # Value is reported in thousands of dollars
    value_str = _find_text(entry, ["value", "VALUE"])
    value_thousands = int(value_str) if value_str and value_str.isdigit() else 0

    # Shares: look in shrsOrPrnAmt sub-element
    shares = 0
    shares_el = _find_element(entry, ["shrsOrPrnAmt", "SHRSORPRNAMT"])
    if shares_el is not None:
        amt = _find_text(shares_el, ["sshPrnamt", "SSHPRNAMT"])
        if amt:
            try:
                shares = int(amt)
            except ValueError:
                shares = 0

    investment_discretion = (
        _find_text(entry, ["investmentDiscretion", "INVESTMENTDISCRETION"]) or "SOLE"
    )

    return {
        "cusip": cusip,
        "name": name,
        "shares": shares,
        "value": value_thousands * 1000,  # Convert to actual dollars
        "investment_discretion": investment_discretion,
    }


def _fetch_13f_info_table(filing: Dict) -> List[Dict]:
    """
    Given a filing metadata dict, fetch and parse its 13F information table.

    The info table is typically a separate XML document within the filing.
    We look for it in the filing index page.
    """
    cik_stripped = filing["cik"].lstrip("0")
    acc_no_dashes = filing["accession_number"].replace("-", "")
    index_url = (
        f"{SEC_ARCHIVES_URL}/Archives/edgar/data/{cik_stripped}/" f"{acc_no_dashes}/index.json"
    )

    resp = _sec_get(index_url)
    if resp is None:
        # Fallback: try the primary document directly
        return _try_primary_document(filing)

    try:
        index_data = resp.json()
    except (json.JSONDecodeError, ValueError):
        return _try_primary_document(filing)

    # Find the information table file in the filing index
    info_table_url = None
    directory = index_data.get("directory", {})
    items = directory.get("item", [])

    for item in items:
        name = item.get("name", "").lower()
        # 13F info table files are typically named *infotable*.xml
        if ("infotable" in name or "information_table" in name) and name.endswith(".xml"):
            info_table_url = (
                f"{SEC_ARCHIVES_URL}/Archives/edgar/data/{cik_stripped}/"
                f"{acc_no_dashes}/{item['name']}"
            )
            break

    # If no XML found, try any .xml file that isn't the primary doc
    if info_table_url is None:
        for item in items:
            name = item.get("name", "").lower()
            if name.endswith(".xml") and "primary" not in name:
                info_table_url = (
                    f"{SEC_ARCHIVES_URL}/Archives/edgar/data/{cik_stripped}/"
                    f"{acc_no_dashes}/{item['name']}"
                )
                break

    if info_table_url is None:
        # Try common info table filenames directly before falling back
        base_url = f"{SEC_ARCHIVES_URL}/Archives/edgar/data/{cik_stripped}/" f"{acc_no_dashes}"
        common_names = [
            "infotable.xml",
            "InfoTable.xml",
            "form13fInfoTable.xml",
            "information_table.xml",
        ]
        for fname in common_names:
            guess_url = f"{base_url}/{fname}"
            resp = _sec_get(guess_url)
            if resp is not None:
                holdings = _parse_13f_xml(resp.text)
                if holdings:
                    return holdings
        return _try_primary_document(filing)

    logger.info("13f_info_table_url", url=info_table_url)
    resp = _sec_get(info_table_url)
    if resp is None:
        return []

    return _parse_13f_xml(resp.text)


def _try_primary_document(filing: Dict) -> List[Dict]:
    """Fallback: try to parse the primary filing document as XML."""
    if not filing.get("primary_document"):
        return []

    cik_stripped = filing["cik"].lstrip("0")
    acc_no_dashes = filing["accession_number"].replace("-", "")
    doc_url = (
        f"{SEC_ARCHIVES_URL}/Archives/edgar/data/{cik_stripped}/"
        f"{acc_no_dashes}/{filing['primary_document']}"
    )

    resp = _sec_get(doc_url)
    if resp is None:
        return []

    # Try XML parse; if it fails, the primary doc may be HTML (cover page)
    holdings = _parse_13f_xml(resp.text)
    return holdings


def fetch_13f_holdings(cik: str, limit: int = 1) -> List[Dict]:
    """
    Fetch the latest 13F filing(s) for an institution and extract holdings.

    Parameters
    ----------
    cik : str
        SEC CIK number (with or without leading zeros).
    limit : int
        Number of recent filings to retrieve (default: 1 = latest only).
        Use limit=2 to also get the previous quarter for QoQ comparison.

    Returns
    -------
    list[dict]
        One dict per filing, each containing:
          - filing_date (str): The date the filing was submitted.
          - holdings (list[dict]): Each holding has:
              - ticker (str): Resolved ticker symbol (or CUSIP if unknown).
              - name (str): Issuer name as reported.
              - cusip (str): 9-character CUSIP identifier.
              - shares (int): Number of shares held.
              - value (float): Market value in dollars.
              - change_pct_qoq (float|None): QoQ change in shares
                (only populated when limit >= 2).

    Notes
    -----
    Results are cached for 24 hours. SEC filings only update quarterly.
    """
    cik_padded = cik.lstrip("0").zfill(10)
    cache_k = _cache_key("fetch_13f_holdings", f"{cik_padded}_{limit}")

    cached = _read_cache(cache_k)
    if cached is not None:
        logger.info("13f_cache_hit", cik=cik_padded, limit=limit)
        return cached

    logger.info("13f_fetch_start", cik=cik_padded, limit=limit)

    # Get filing metadata
    filings_meta = _get_filing_urls(cik_padded, limit=max(limit, 2))
    if not filings_meta:
        logger.warning("13f_no_filings_found", cik=cik_padded)
        return []

    results = []
    all_holdings_by_filing = []

    for meta in filings_meta[:limit]:
        raw_holdings = _fetch_13f_info_table(meta)
        logger.info(
            "13f_parsed",
            cik=cik_padded,
            filing_date=meta["filing_date"],
            num_holdings=len(raw_holdings),
        )

        # Resolve CUSIPs to tickers
        enriched = []
        for h in raw_holdings:
            ticker = _cusip_to_ticker(h["cusip"])
            enriched.append(
                {
                    "ticker": ticker,
                    "name": h["name"],
                    "cusip": h["cusip"],
                    "shares": h["shares"],
                    "value": h["value"],
                    "change_pct_qoq": None,  # Filled in below if we have prior data
                }
            )

        all_holdings_by_filing.append(enriched)
        results.append(
            {
                "filing_date": meta["filing_date"],
                "holdings": enriched,
            }
        )

    # Compute QoQ changes if we have two filings
    if limit >= 2 and len(filings_meta) >= 2:
        # Fetch previous quarter holdings for comparison
        prev_meta = filings_meta[1] if len(filings_meta) > 1 else None
        if prev_meta and len(all_holdings_by_filing) >= 1:
            prev_holdings = _fetch_13f_info_table(prev_meta)
            prev_by_cusip = {h["cusip"]: h for h in prev_holdings}

            # Annotate latest holdings with QoQ change
            for h in results[0]["holdings"]:
                prev = prev_by_cusip.get(h["cusip"])
                if prev and prev["shares"] > 0:
                    h["change_pct_qoq"] = round(
                        ((h["shares"] - prev["shares"]) / prev["shares"]) * 100, 2
                    )
                elif prev is None:
                    # New position
                    h["change_pct_qoq"] = None  # Marked as new in changes endpoint

    _write_cache(cache_k, results)
    logger.info("13f_fetch_complete", cik=cik_padded, num_filings=len(results))
    return results


# ══════════════════════════════════════════════════════════════
#  Section 3 — Institutional Ownership for a Given Ticker
# ══════════════════════════════════════════════════════════════


def get_institutional_ownership(
    ticker: str,
    institutions: Optional[List[Dict]] = None,
) -> Dict:
    """
    Find which top institutions hold a given stock.

    Cross-references the ticker across the latest 13F filings
    of all tracked institutions.

    Parameters
    ----------
    ticker : str
        Stock ticker symbol (e.g., 'AAPL').
    institutions : list[dict], optional
        Custom list of institutions to check. If None, uses
        get_top_institutions() (the default top ~30).

    Returns
    -------
    dict
        {
            'ticker': str,
            'institutions': [
                {
                    'name': str,
                    'shares': int,
                    'value': float,
                    'pct_of_portfolio': float  (0-100)
                }
            ],
            'total_institutional_shares': int,
            'total_institutional_value': float,
            'crowding_score': float  (0.0 - 1.0)
        }

    Notes
    -----
    crowding_score = (number of top 30 institutions holding) / 30
    """
    if institutions is None:
        institutions = get_top_institutions()

    cache_k = _cache_key("get_inst_ownership", ticker.upper())
    cached = _read_cache(cache_k)
    if cached is not None:
        return cached

    ticker_upper = ticker.upper()
    target_cusips = set(TICKER_TO_CUSIPS.get(ticker_upper, []))

    holders = []
    total_shares = 0
    total_value = 0.0

    logger.info("ownership_scan_start", ticker=ticker_upper, num_institutions=len(institutions))

    for inst in institutions:
        try:
            filings = fetch_13f_holdings(inst["cik"], limit=1)
            if not filings or not filings[0].get("holdings"):
                continue

            holdings = filings[0]["holdings"]
            portfolio_total_value = sum(h["value"] for h in holdings)

            # Find this ticker in the institution's holdings
            for h in holdings:
                matches_ticker = h["ticker"].upper() == ticker_upper
                matches_cusip = h["cusip"] in target_cusips

                if matches_ticker or matches_cusip:
                    pct_of_portfolio = (
                        (h["value"] / portfolio_total_value * 100)
                        if portfolio_total_value > 0
                        else 0.0
                    )
                    holders.append(
                        {
                            "name": inst["name"],
                            "shares": h["shares"],
                            "value": h["value"],
                            "pct_of_portfolio": round(pct_of_portfolio, 4),
                        }
                    )
                    total_shares += h["shares"]
                    total_value += h["value"]
                    break  # Only count each institution once per ticker

        except Exception as exc:
            logger.warning(
                "ownership_fetch_error",
                institution=inst["name"],
                error=str(exc),
            )
            continue

    # Sort by value descending
    holders.sort(key=lambda x: x["value"], reverse=True)

    num_institutions = len(institutions)
    crowding_score = round(len(holders) / num_institutions, 4) if num_institutions > 0 else 0.0

    result = {
        "ticker": ticker_upper,
        "institutions": holders,
        "total_institutional_shares": total_shares,
        "total_institutional_value": total_value,
        "crowding_score": crowding_score,
    }

    _write_cache(cache_k, result)
    logger.info(
        "ownership_scan_complete",
        ticker=ticker_upper,
        num_holders=len(holders),
        crowding_score=crowding_score,
    )
    return result


# ══════════════════════════════════════════════════════════════
#  Section 4 — Smart Money Signals for Portfolio
# ══════════════════════════════════════════════════════════════


def get_smart_money_signals(portfolio_tickers: List[str]) -> List[Dict]:
    """
    Analyze institutional conviction for each holding in a user's portfolio.

    For each ticker, checks how many top institutions hold it,
    computes a crowding score, and assigns a conviction signal.

    Parameters
    ----------
    portfolio_tickers : list[str]
        List of ticker symbols in the user's portfolio.

    Returns
    -------
    list[dict]
        Sorted by num_institutions descending. Each dict:
        {
            'ticker': str,
            'num_institutions': int,
            'crowding_score': float (0.0-1.0),
            'top_holders': [str],  # names of top 5 institutional holders
            'signal': str  # 'HIGH_CONVICTION', 'MODERATE', or 'LOW'
        }

    Signal Thresholds
    -----------------
    - HIGH_CONVICTION: >10 of top 30 funds hold the stock
    - MODERATE: 5-10 of top 30 funds hold the stock
    - LOW: <5 of top 30 funds hold the stock
    """
    if not portfolio_tickers:
        return []

    cache_k = _cache_key(
        "smart_money_signals",
        "_".join(sorted(t.upper() for t in portfolio_tickers)),
    )
    cached = _read_cache(cache_k)
    if cached is not None:
        return cached

    logger.info("smart_money_scan_start", num_tickers=len(portfolio_tickers))

    # Pre-fetch all institution filings (will be cached individually)
    institutions = get_top_institutions()
    institution_holdings = {}  # cik -> holdings list

    for inst in institutions:
        try:
            filings = fetch_13f_holdings(inst["cik"], limit=1)
            if filings and filings[0].get("holdings"):
                institution_holdings[inst["cik"]] = {
                    "name": inst["name"],
                    "holdings": filings[0]["holdings"],
                }
        except Exception as exc:
            logger.warning(
                "smart_money_prefetch_error",
                institution=inst["name"],
                error=str(exc),
            )

    results = []

    for ticker in portfolio_tickers:
        ticker_upper = ticker.upper()
        target_cusips = set(TICKER_TO_CUSIPS.get(ticker_upper, []))

        holders = []
        for cik, inst_data in institution_holdings.items():
            for h in inst_data["holdings"]:
                matches_ticker = h["ticker"].upper() == ticker_upper
                matches_cusip = h["cusip"] in target_cusips

                if matches_ticker or matches_cusip:
                    holders.append(inst_data["name"])
                    break

        num_holders = len(holders)
        num_total = len(institutions)
        crowding = round(num_holders / num_total, 4) if num_total > 0 else 0.0

        # Assign signal
        if num_holders > 10:
            signal = "HIGH_CONVICTION"
        elif num_holders >= 5:
            signal = "MODERATE"
        else:
            signal = "LOW"

        results.append(
            {
                "ticker": ticker_upper,
                "num_institutions": num_holders,
                "crowding_score": crowding,
                "top_holders": holders[:5],
                "signal": signal,
            }
        )

    # Sort by institutional conviction descending
    results.sort(key=lambda x: x["num_institutions"], reverse=True)

    _write_cache(cache_k, results)
    logger.info(
        "smart_money_scan_complete",
        num_tickers=len(portfolio_tickers),
        high_conviction=sum(1 for r in results if r["signal"] == "HIGH_CONVICTION"),
        moderate=sum(1 for r in results if r["signal"] == "MODERATE"),
        low=sum(1 for r in results if r["signal"] == "LOW"),
    )
    return results


# ══════════════════════════════════════════════════════════════
#  Section 5 — Quarter-over-Quarter Institutional Changes
# ══════════════════════════════════════════════════════════════


def get_institutional_changes(cik: str) -> Dict:
    """
    Compare an institution's latest vs. previous 13F filing to detect
    quarter-over-quarter position changes.

    Parameters
    ----------
    cik : str
        SEC CIK number of the institution.

    Returns
    -------
    dict
        {
            'institution_cik': str,
            'latest_filing_date': str,
            'previous_filing_date': str | None,
            'new_positions': [
                {'ticker': str, 'name': str, 'shares': int, 'value': float}
            ],
            'increased': [
                {'ticker': str, 'name': str, 'shares': int, 'value': float,
                 'change_pct': float, 'prev_shares': int}
            ],
            'decreased': [
                {'ticker': str, 'name': str, 'shares': int, 'value': float,
                 'change_pct': float, 'prev_shares': int}
            ],
            'exited': [
                {'ticker': str, 'name': str, 'prev_shares': int, 'prev_value': float}
            ],
            'unchanged_count': int,
            'summary': {
                'total_new': int,
                'total_increased': int,
                'total_decreased': int,
                'total_exited': int,
            }
        }
    """
    cik_padded = cik.lstrip("0").zfill(10)
    cache_k = _cache_key("inst_changes", cik_padded)
    cached = _read_cache(cache_k)
    if cached is not None:
        return cached

    logger.info("institutional_changes_start", cik=cik_padded)

    # Fetch the two most recent filings
    filings_meta = _get_filing_urls(cik_padded, limit=2)
    if not filings_meta:
        logger.warning("institutional_changes_no_filings", cik=cik_padded)
        return {
            "institution_cik": cik_padded,
            "latest_filing_date": None,
            "previous_filing_date": None,
            "new_positions": [],
            "increased": [],
            "decreased": [],
            "exited": [],
            "unchanged_count": 0,
            "summary": {
                "total_new": 0,
                "total_increased": 0,
                "total_decreased": 0,
                "total_exited": 0,
            },
        }

    # Parse latest filing
    latest_raw = _fetch_13f_info_table(filings_meta[0])
    latest_by_cusip = {}
    for h in latest_raw:
        ticker = _cusip_to_ticker(h["cusip"])
        latest_by_cusip[h["cusip"]] = {
            "ticker": ticker,
            "name": h["name"],
            "cusip": h["cusip"],
            "shares": h["shares"],
            "value": h["value"],
        }

    # Parse previous filing (if available)
    prev_by_cusip = {}
    previous_filing_date = None
    if len(filings_meta) >= 2:
        previous_filing_date = filings_meta[1]["filing_date"]
        prev_raw = _fetch_13f_info_table(filings_meta[1])
        for h in prev_raw:
            ticker = _cusip_to_ticker(h["cusip"])
            prev_by_cusip[h["cusip"]] = {
                "ticker": ticker,
                "name": h["name"],
                "cusip": h["cusip"],
                "shares": h["shares"],
                "value": h["value"],
            }

    # Compute changes
    new_positions = []
    increased = []
    decreased = []
    exited = []
    unchanged_count = 0

    all_cusips = set(latest_by_cusip.keys()) | set(prev_by_cusip.keys())

    for cusip in all_cusips:
        in_latest = cusip in latest_by_cusip
        in_prev = cusip in prev_by_cusip

        if in_latest and not in_prev:
            # New position
            h = latest_by_cusip[cusip]
            new_positions.append(
                {
                    "ticker": h["ticker"],
                    "name": h["name"],
                    "shares": h["shares"],
                    "value": h["value"],
                }
            )

        elif not in_latest and in_prev:
            # Exited position
            h = prev_by_cusip[cusip]
            exited.append(
                {
                    "ticker": h["ticker"],
                    "name": h["name"],
                    "prev_shares": h["shares"],
                    "prev_value": h["value"],
                }
            )

        elif in_latest and in_prev:
            curr = latest_by_cusip[cusip]
            prev = prev_by_cusip[cusip]
            share_diff = curr["shares"] - prev["shares"]

            if share_diff == 0:
                unchanged_count += 1
            else:
                change_pct = (
                    round((share_diff / prev["shares"]) * 100, 2) if prev["shares"] > 0 else 0.0
                )
                entry = {
                    "ticker": curr["ticker"],
                    "name": curr["name"],
                    "shares": curr["shares"],
                    "value": curr["value"],
                    "change_pct": change_pct,
                    "prev_shares": prev["shares"],
                }
                if share_diff > 0:
                    increased.append(entry)
                else:
                    decreased.append(entry)

    # Sort by absolute change magnitude
    new_positions.sort(key=lambda x: x["value"], reverse=True)
    increased.sort(key=lambda x: abs(x["change_pct"]), reverse=True)
    decreased.sort(key=lambda x: abs(x["change_pct"]), reverse=True)
    exited.sort(key=lambda x: x["prev_value"], reverse=True)

    result = {
        "institution_cik": cik_padded,
        "latest_filing_date": filings_meta[0]["filing_date"],
        "previous_filing_date": previous_filing_date,
        "new_positions": new_positions,
        "increased": increased,
        "decreased": decreased,
        "exited": exited,
        "unchanged_count": unchanged_count,
        "summary": {
            "total_new": len(new_positions),
            "total_increased": len(increased),
            "total_decreased": len(decreased),
            "total_exited": len(exited),
        },
    }

    _write_cache(cache_k, result)
    logger.info(
        "institutional_changes_complete",
        cik=cik_padded,
        new=len(new_positions),
        increased=len(increased),
        decreased=len(decreased),
        exited=len(exited),
        unchanged=unchanged_count,
    )
    return result


# ══════════════════════════════════════════════════════════════
#  Convenience / Summary Helpers
# ══════════════════════════════════════════════════════════════


def get_institution_name(cik: str) -> Optional[str]:
    """Look up the display name for a CIK from our tracked institutions."""
    cik_padded = cik.lstrip("0").zfill(10)
    for inst in _TOP_INSTITUTIONS:
        if inst[1] == cik_padded:
            return inst[0]
    return None


def get_institution_cik(name: str) -> Optional[str]:
    """Look up the CIK for an institution by (partial, case-insensitive) name."""
    name_lower = name.lower()
    for inst_name, cik in _TOP_INSTITUTIONS:
        if name_lower in inst_name.lower():
            return cik
    return None


def summarize_top_holdings(cik: str, top_n: int = 20) -> List[Dict]:
    """
    Quick summary of an institution's top N holdings by value.

    Returns
    -------
    list[dict]
        Each: {ticker, name, shares, value, pct_of_portfolio}
    """
    filings = fetch_13f_holdings(cik, limit=1)
    if not filings or not filings[0].get("holdings"):
        return []

    holdings = filings[0]["holdings"]
    total_value = sum(h["value"] for h in holdings)

    # Sort by value descending
    sorted_holdings = sorted(holdings, key=lambda x: x["value"], reverse=True)

    result = []
    for h in sorted_holdings[:top_n]:
        pct = round((h["value"] / total_value * 100), 4) if total_value > 0 else 0.0
        result.append(
            {
                "ticker": h["ticker"],
                "name": h["name"],
                "shares": h["shares"],
                "value": h["value"],
                "pct_of_portfolio": pct,
            }
        )

    return result


def clear_cache() -> int:
    """
    Clear all cached 13F data. Returns the number of files removed.

    Useful when you want to force a fresh pull of all filing data.
    """
    if not os.path.exists(CACHE_DIR):
        return 0

    count = 0
    for fname in os.listdir(CACHE_DIR):
        fpath = os.path.join(CACHE_DIR, fname)
        if os.path.isfile(fpath):
            try:
                os.remove(fpath)
                count += 1
            except OSError:
                pass

    logger.info("cache_cleared", files_removed=count)
    return count
