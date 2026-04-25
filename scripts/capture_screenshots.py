"""
scripts/capture_screenshots.py

Drive a headless browser through the Streamlit app to produce README
screenshots that reliably reflect the app's real UI.

Key principles (fixing earlier screenshot drift):
  1. Each target declares a `verify` substring — title or visible text
     that MUST appear before we screenshot. Otherwise we fail fast.
  2. Interactive pages are actually *driven*: Ticker Research gets a
     ticker typed into its search box; Trading Floor gets "Load Market
     Data" clicked.
  3. We crop to above-the-fold (viewport height) instead of full_page
     so screenshots don't trail off into huge empty space.
  4. If a page is still empty / showing a guard state after all waits,
     we DON'T save the image — the README is not to lie about coverage.

Usage:
    streamlit run app.py --server.headless true --server.port 8610 &
    STREAMLIT_BASE_URL=http://localhost:8610 python scripts/capture_screenshots.py
"""

from __future__ import annotations

import os
import pathlib
import sys
import time

from playwright.sync_api import Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout

BASE_URL = os.environ.get("STREAMLIT_BASE_URL", "http://localhost:8610")
OUT_DIR = pathlib.Path(__file__).parent.parent / "docs" / "screenshots"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Viewport for desktop screenshots — tall enough to catch first-fold content
VIEWPORT = {"width": 1440, "height": 1000}

# Full-page empty-state markers rendered by render_empty_state().
# These are the big dark cards that completely replace the page content,
# not mere inline hints. Only these warrant refusing to save a screenshot.
EMPTY_STATE_MARKERS = [
    "No analysis yet",
    "Risk analytics require a portfolio",
    "Markets need a portfolio to contextualize",
    "Portfolio tools need analysis data",
]


def _dismiss_splash(page: Page) -> None:
    """Streamlit occasionally shows a 'Manage app' tooltip — dismiss it."""
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass


def _wait_hydrated(page: Page, max_s: float = 10.0) -> None:
    """Wait until the JS shell hydrates (h1/h2/button shows up)."""
    deadline = time.time() + max_s
    while time.time() < deadline:
        try:
            if page.locator("h1, h2").count() > 0:
                return
            if page.locator("[data-testid='stAppViewContainer']").count() > 0:
                break
        except Exception:
            pass
        time.sleep(0.25)


def _visible_text_sample(page: Page, limit: int = 4000) -> str:
    """Concatenated text content of body — used for verify + empty-state."""
    try:
        return page.evaluate("() => document.body.innerText")[:limit]
    except Exception:
        return ""


def _is_empty_state(page: Page) -> bool:
    body = _visible_text_sample(page)
    return any(marker in body for marker in EMPTY_STATE_MARKERS)


def _capture_landing(page: Page, out: pathlib.Path) -> bool:
    page.goto(BASE_URL + "/", wait_until="domcontentloaded", timeout=25_000)
    _wait_hydrated(page)
    _dismiss_splash(page)
    time.sleep(3)
    # Verify it's actually the landing
    body = _visible_text_sample(page)
    if "MindMarket" not in body:
        print("  ! landing not rendered (title missing)")
        return False
    # Crop to viewport (above the fold)
    page.screenshot(path=str(out), full_page=False)
    return True


def _nav_to(page: Page, link_text: str, timeout: int = 5000) -> bool:
    """Click a multi-page navigation link. Start from home first."""
    page.goto(BASE_URL + "/", wait_until="domcontentloaded", timeout=25_000)
    _wait_hydrated(page)
    time.sleep(2)
    try:
        page.locator(f'a:has-text("{link_text}")').first.click(timeout=timeout)
        return True
    except PlaywrightTimeout:
        return False


def _capture_tradingview(page: Page, out: pathlib.Path) -> bool:
    if not _nav_to(page, "TradingView"):
        print("  ! nav to TradingView failed")
        return False
    time.sleep(7)  # TradingView widget iframe needs time
    body = _visible_text_sample(page)
    if "TradingView" not in body and "Charts" not in body:
        print("  ! TradingView page didn't render")
        return False
    page.screenshot(path=str(out), full_page=False)
    return True


def _capture_ticker_research(page: Page, out: pathlib.Path, search_ticker: str = "NVDA") -> bool:
    """Auto-populate a ticker and run the search so the screenshot has data."""
    # Start at home then click nav link — direct URL navigation is unreliable
    # for Streamlit multi-page apps (falls back to home if internal router
    # hasn't registered the page yet).
    page.goto(BASE_URL + "/", wait_until="domcontentloaded", timeout=25_000)
    _wait_hydrated(page)
    time.sleep(2)

    # Click the "Ticker Research" link in the multi-page nav
    try:
        page.locator('a:has-text("Ticker Research"), a:has-text("Ticker_Research")').first.click(
            timeout=5000
        )
    except PlaywrightTimeout:
        print("  ! nav link to Ticker Research not found")
        return False

    time.sleep(5)  # wait for page to hydrate

    # Find the page's own ticker input (aria-label="Ticker Symbol")
    filled = False
    try:
        target = page.locator('input[aria-label="Ticker Symbol"], input[aria-label="股票代码"]')
        if target.count() > 0:
            target.first.fill(search_ticker)
            target.first.press("Enter")
            filled = True
    except Exception:
        pass

    if not filled:
        # Fallback: find any input whose surrounding label says "Ticker Symbol"
        try:
            for blk in page.locator('[data-testid="stTextInput"]').all():
                lbl = (blk.locator("label").text_content() or "").lower()
                if "ticker" in lbl and "api" not in lbl:  # exclude FMP/Claude keys
                    inp = blk.locator("input")
                    if inp.count():
                        inp.first.fill(search_ticker)
                        inp.first.press("Enter")
                        filled = True
                        break
        except Exception as e:
            print(f"  ! fallback input search failed: {e}")

    if not filled:
        print("  ! ticker input not found on page")
        return False

    # Click the Search button to be explicit
    try:
        page.locator('button:has-text("Search"), button:has-text("搜索")').first.click(timeout=3000)
    except PlaywrightTimeout:
        pass

    # Research fetch + render (FMP calls may take 10-15s)
    time.sleep(12)
    body = _visible_text_sample(page)
    if not any(k in body for k in ("Fundamentals", "Valuation", "Analyst", search_ticker)):
        print("  ! research sections missing — still empty")
        return False
    page.screenshot(path=str(out), full_page=False)
    return True


def _capture_trading_floor(page: Page, out: pathlib.Path) -> bool:
    """Click 'Load Market Data' button so the floor shows real content."""
    if not _nav_to(page, "Trading Floor"):
        print("  ! nav to Trading Floor failed")
        return False
    time.sleep(3)

    # Click LOAD MARKET DATA button
    btn = page.locator('button:has-text("LOAD MARKET DATA"), button:has-text("加载市场数据")')
    try:
        btn.first.click(timeout=4000)
    except PlaywrightTimeout:
        print("  ! LOAD MARKET DATA button not found")
        return False

    # Wait for regime + movers + sectors to populate (30+ seconds realistic)
    time.sleep(20)
    body = _visible_text_sample(page)
    if "TRADING FLOOR MONITOR" not in body.upper():
        print("  ! trading floor header missing")
        return False
    page.screenshot(path=str(out), full_page=False)
    return True


TARGETS = [
    ("01_landing.png", _capture_landing),
    ("02_tradingview.png", _capture_tradingview),
    ("03_ticker_research.png", _capture_ticker_research),
    ("04_trading_floor.png", _capture_trading_floor),
]


def capture():
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for filename, fn in TARGETS:
                # Fresh context per page so state doesn't bleed
                ctx = browser.new_context(viewport=VIEWPORT, device_scale_factor=2)
                page = ctx.new_page()
                out = OUT_DIR / filename
                print(f"→ {filename} via {fn.__name__}")
                ok = False
                try:
                    ok = fn(page, out)
                except Exception as e:
                    print(f"   ! capture error: {e}")

                if ok:
                    # Reject if empty state detected (UI barrier)
                    if _is_empty_state(page):
                        print("   ! empty-state page — NOT saving")
                        if out.exists():
                            out.unlink()
                        ok = False
                    else:
                        size_kb = out.stat().st_size / 1024 if out.exists() else 0
                        print(f"   ✓ saved {size_kb:.0f} KB")
                results.append((filename, ok))
                ctx.close()
        finally:
            browser.close()

    successes = sum(1 for _, ok in results if ok)
    print(f"\nCaptured {successes}/{len(results)} screenshots.")
    if successes < len(results):
        # Non-zero exit if any capture failed — CI should catch drift
        sys.exit(2 if successes == 0 else 1)


if __name__ == "__main__":
    print(f"BASE_URL = {BASE_URL}")
    capture()
