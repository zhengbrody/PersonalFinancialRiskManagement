"""
scripts/capture_screenshots.py

Drive a headless browser through the Streamlit app and save a handful of
screenshots to docs/screenshots/ for README embedding.

Usage (with Streamlit already running on port 8610):
    streamlit run app.py --server.headless true --server.port 8610 &
    python scripts/capture_screenshots.py

Screenshots captured:
  - 01_landing.png         Landing / hero (no analysis required)
  - 02_tradingview.png     Page 5 — works without portfolio analysis
  - 03_ticker_research.png Page 10 — standalone ticker lookup
  - 04_trading_floor.png   Page 7 — default watchlist works

Pages that require Run Analysis (Overview / Risk / Markets / Portfolio /
Options / Institutions / Quant Lab) are NOT captured here — they need
live API keys and ~30-60s of computation which this script can't guarantee.
"""
from __future__ import annotations

import pathlib
import sys
import time

from playwright.sync_api import sync_playwright

import os
BASE_URL = os.environ.get("STREAMLIT_BASE_URL", "http://localhost:8610")
OUT_DIR = pathlib.Path(__file__).parent.parent / "docs" / "screenshots"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Streamlit multi-page apps strip the leading `N_` prefix from filenames.
# pages/5_TradingView.py -> /TradingView (NOT /5_TradingView)
#
# (url_suffix, output filename, wait_for_selector or None, extra_wait_seconds)
TARGETS = [
    ("/",                 "01_landing.png",           "h1",    6),
    ("/TradingView",      "02_tradingview.png",        None,   8),
    ("/Ticker_Research",  "03_ticker_research.png",    None,   6),
    ("/Trading_Floor",    "04_trading_floor.png",      None,   8),
]

VIEWPORT = {"width": 1440, "height": 1800}


def capture():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for suffix, filename, selector, wait_s in TARGETS:
                # Fresh context per page to guarantee isolated navigation
                # (Streamlit multi-page routing can confuse a reused page object)
                ctx = browser.new_context(viewport=VIEWPORT, device_scale_factor=2)
                page = ctx.new_page()

                url = BASE_URL + suffix
                print(f"→ {url}")
                try:
                    page.goto(url, wait_until="networkidle", timeout=30_000)
                except Exception as e:
                    print(f"   ! networkidle timed out, proceeding: {e}")

                if selector:
                    try:
                        page.wait_for_selector(selector, timeout=10_000)
                    except Exception:
                        pass

                # Streamlit hydrates after websocket handshake — give it time
                time.sleep(wait_s)
                # A second pass to catch late-rendering Plotly / tabs
                try:
                    page.wait_for_load_state("networkidle", timeout=8_000)
                except Exception:
                    pass
                time.sleep(1.5)

                out = OUT_DIR / filename
                page.screenshot(path=str(out), full_page=True)
                size_kb = out.stat().st_size / 1024 if out.exists() else 0
                print(f"   ✓ saved {out.name} ({size_kb:.0f} KB)")
                ctx.close()
        finally:
            browser.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--base":
        BASE_URL = sys.argv[2]
    print(f"Using BASE_URL = {BASE_URL}")
    capture()
    print("\nDone.")
