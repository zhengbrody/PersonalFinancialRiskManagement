from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[2]
SEO_DIR = ROOT / "assets" / "seo"

STATIC_ROUTES = {
    "/about": "about.html",
    "/demo": "demo.html",
    "/sample-risk-report": "sample-risk-report.html",
    "/portfolio-risk-management": "portfolio-risk-management.html",
    "/ai-portfolio-analysis": "ai-portfolio-analysis.html",
    "/portfolio-var-stress-testing": "portfolio-var-stress-testing.html",
    "/personal-portfolio-risk-analysis": "personal-portfolio-risk-analysis.html",
    "/margin-risk-calculator": "margin-risk-calculator.html",
    "/portfolio-stress-test": "portfolio-stress-test.html",
    "/stock-portfolio-concentration-risk": "stock-portfolio-concentration-risk.html",
    "/robinhood-margin-risk": "robinhood-margin-risk.html",
}


def _sitemap_paths() -> set[str]:
    tree = ElementTree.parse(SEO_DIR / "sitemap.xml")
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    paths = set()
    for loc in tree.findall(".//sm:loc", ns):
        text = loc.text or ""
        assert text.startswith("https://mindmarket.app")
        path = text.removeprefix("https://mindmarket.app")
        paths.add(path or "/")
    return paths


def test_sitemap_contains_growth_routes():
    paths = _sitemap_paths()

    assert "/" in paths
    assert "/Legal" in paths
    for route in STATIC_ROUTES:
        assert route in paths


def test_static_routes_have_files_and_caddy_handles():
    caddyfile = (ROOT / "Caddyfile").read_text(encoding="utf-8")

    for route, filename in STATIC_ROUTES.items():
        assert (SEO_DIR / filename).exists()
        assert f"handle {route}" in caddyfile
        assert f"rewrite * /{filename}" in caddyfile


def test_seo_pages_have_canonical_description_and_cta():
    for route, filename in STATIC_ROUTES.items():
        html = (SEO_DIR / filename).read_text(encoding="utf-8")

        assert f'<link rel="canonical" href="https://mindmarket.app{route}">' in html
        assert '<meta name="description" content="' in html
        assert "https://mindmarket.app/" in html
        lowered = html.lower()
        assert "investment" in lowered
        assert "advice" in lowered


def test_robots_points_to_sitemap():
    robots = (SEO_DIR / "robots.txt").read_text(encoding="utf-8")

    assert "User-agent: *" in robots
    assert "Allow: /" in robots
    assert "Sitemap: https://mindmarket.app/sitemap.xml" in robots
