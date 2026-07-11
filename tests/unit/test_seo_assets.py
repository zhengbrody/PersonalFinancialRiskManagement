"""SEO migration invariants — the static assets/seo pages are now Next.js routes.

A single SEO content source: the old static HTML + robots/sitemap are removed,
Caddy no longer serves them, and every migrated URL has a Next route so nothing
404s. (Sitemap/robots/canonical CONTENT is asserted in the frontend suite —
frontend/src/app/seo-routes.test.ts.)
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEO_DIR = ROOT / "assets" / "seo"
APP = ROOT / "frontend" / "src" / "app"

# Former static SEO pages → their Next route segment.
MIGRATED_ROUTES = {
    "/about": "about",
    "/sample-risk-report": "sample-risk-report",
    "/portfolio-risk-management": "portfolio-risk-management",
    "/ai-portfolio-analysis": "ai-portfolio-analysis",
    "/portfolio-var-stress-testing": "portfolio-var-stress-testing",
    "/personal-portfolio-risk-analysis": "personal-portfolio-risk-analysis",
    "/margin-risk-calculator": "margin-risk-calculator",
    "/portfolio-stress-test": "portfolio-stress-test",
    "/stock-portfolio-concentration-risk": "stock-portfolio-concentration-risk",
    "/robinhood-margin-risk": "robinhood-margin-risk",
}

_OLD_FILES = (
    [f"{seg}.html" for seg in MIGRATED_ROUTES.values()]
    + ["demo.html", "robots.txt", "sitemap.xml"]
)


def test_static_seo_files_removed():
    """The old static pages + static robots/sitemap are gone (single Next source)."""
    for f in _OLD_FILES:
        assert not (SEO_DIR / f).exists(), f"static SEO file {f} should be migrated to Next.js"


def test_caddy_no_longer_serves_static_seo():
    caddyfile = (ROOT / "Caddyfile").read_text(encoding="utf-8")
    assert "root * /srv/seo" not in caddyfile, "Caddy still serves a static /srv/seo page"
    for route in list(MIGRATED_ROUTES) + ["/demo", "/robots.txt", "/sitemap.xml"]:
        assert f"handle {route} {{" not in caddyfile, f"stale Caddy handle for {route}"
    # The final catch-all to the Next frontend must remain.
    assert "reverse_proxy frontend:3000" in caddyfile


def test_migrated_urls_have_next_routes():
    """Every migrated URL now resolves to a Next route — nothing is orphaned."""
    for route, seg in MIGRATED_ROUTES.items():
        assert (APP / seg / "page.tsx").exists(), f"missing Next page for {route}"
    # /demo is a permanent 301 route handler (→ /demo-risk-check), not a page.
    assert (APP / "demo" / "route.ts").exists(), "missing /demo 301 route handler"
    assert (APP / "demo-risk-check").exists(), "301 target /demo-risk-check missing"
