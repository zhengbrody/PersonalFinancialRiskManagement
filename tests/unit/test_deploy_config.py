from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_split_compose_passes_supabase_service_key_to_server_only_backend_env():
    # The service-role key moved from the retired Streamlit `app` (compose.aws.yml)
    # to the backend (compose.split.yml) when Streamlit was retired — see CLAUDE.md
    # §1B. It must still be forwarded server-side and documented as never-in-UI.
    compose = (ROOT / "compose.split.yml").read_text(encoding="utf-8")

    assert "SUPABASE_SERVICE_KEY=${SUPABASE_SERVICE_KEY:-}" in compose
    assert "server-only" in compose
    assert "must never be rendered in the UI" in compose


def test_deploy_script_forwards_supabase_service_key_from_secrets_to_env_file():
    deploy_script = (ROOT / "infra" / "scripts" / "deploy-phase-1.sh").read_text(encoding="utf-8")

    assert "SUPABASE_SERVICE_KEY" in deploy_script
    assert "trusted owner/admin cost dashboards" in deploy_script


def test_caddyfile_ships_the_security_headers():
    """The production security headers live in the COMMITTED Caddyfile (boot
    does `git reset --hard`, so only committed config survives). Static guard:
    every required header is present, the CSP is Report-Only for stage 1, and
    no lazy wildcard default-src sneaks in."""
    caddyfile = (ROOT / "Caddyfile").read_text()

    for required in (
        'Strict-Transport-Security "max-age=31536000; includeSubDomains"',
        'X-Content-Type-Options "nosniff"',
        'Referrer-Policy "strict-origin-when-cross-origin"',
        'X-Frame-Options "DENY"',
        "Permissions-Policy",
        'Cross-Origin-Opener-Policy "same-origin-allow-popups"',
        "Content-Security-Policy-Report-Only",
    ):
        assert required in caddyfile, f"missing security header: {required}"

    csp = next(
        line for line in caddyfile.splitlines() if "Content-Security-Policy-Report-Only" in line
    )
    # Stage 1 is OBSERVE-ONLY: the enforcing header must not exist yet.
    assert 'Content-Security-Policy "' not in caddyfile
    # No wildcard default-src (task constraint) — and the origins every
    # runtime dependency needs are all present.
    assert "default-src *" not in csp
    assert "default-src 'self'" in csp
    for origin in (
        "supabase.co",  # auth + REST (+ wss)
        "posthog.com",  # analytics events + remote config
        "ingest.us.sentry.io",  # error ingest + the CSP report-uri
        "accounts.google.com",  # Supabase Google OAuth redirect (form-action)
        "frame-ancestors 'none'",
        "report-uri",
    ):
        assert origin in csp, f"CSP missing: {origin}"


def test_static_seo_pages_use_self_hosted_fonts_only():
    """The static SEO pages must not call out to Google Fonts (CSP tightness +
    privacy); they use the committed self-hosted Instrument Serif instead,
    served by the Caddy /fonts/* handler."""
    seo_pages = sorted((ROOT / "assets/seo").glob("*.html"))
    assert seo_pages, "assets/seo pages missing"
    for page in seo_pages:
        text = page.read_text()
        assert "fonts.googleapis" not in text, f"{page.name} still loads Google Fonts CSS"
        assert "fonts.gstatic" not in text, f"{page.name} still preconnects to gstatic"
        if "Instrument Serif" in text:
            assert "@font-face" in text, f"{page.name} uses the serif without a self-hosted source"

    for font in (
        "assets/brand/fonts/instrument-serif-regular.woff2",
        "assets/brand/fonts/instrument-serif-italic.woff2",
    ):
        assert (ROOT / font).exists(), f"missing committed font file: {font}"

    caddyfile = (ROOT / "Caddyfile").read_text()
    assert "handle /fonts/*" in caddyfile, "Caddy /fonts/* handler missing"
