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


def test_split_compose_forwards_every_backend_feature_flag_and_key():
    """A setting the code reads but compose does not forward is invisible.

    Values live in the EC2 `.env`; docker compose only injects the variables
    named here. A flag left out silently stays at its default, so the feature
    looks broken with nothing in the logs (the MASSIVE_API_KEY class of bug,
    CLAUDE.md §2.18). Any new `_env_str`/`_env_bool` setting read by the
    backend belongs in this list.
    """
    compose = (ROOT / "compose.split.yml").read_text(encoding="utf-8")

    for variable in (
        "MINDMARKET_COMPARISON_REPLAY_ENABLED",
        "MINDMARKET_COMPARISON_SAVE_ENABLED",
        "MINDMARKET_RISK_RUN_SIGNING_SECRET",
        "MINDMARKET_COPILOT_RUNS_ENABLED",
        "MINDMARKET_SHARE_SIGNING_SECRET",
        "PUBLIC_RISK_CHECK_ENABLED",
    ):
        assert f"{variable}=${{{variable}" in compose, f"{variable} is not forwarded to backend"


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

    # Script hosts derived from the Report-Only stream, not guessed: PostHog
    # serves its runtime extension bundles as SCRIPTS from the assets host
    # (connect-src does not cover script loads), and Cloudflare injects the RUM
    # beacon at the edge. Enforcing without these silently kills analytics.
    script_src = next(part for part in csp.split(";") if part.strip().startswith("script-src"))
    for host in ("https://us-assets.i.posthog.com", "https://static.cloudflareinsights.com"):
        assert host in script_src, f"script-src missing: {host}"

    # 'unsafe-eval' must stay OUT: it re-permits the injection class the policy
    # exists to stop. The `eval:` reports came from Zod v4's JIT probe, which is
    # disabled at source (frontend/src/lib/zod-config.ts) instead.
    assert "unsafe-eval" not in csp
    zod_config = (ROOT / "frontend/src/lib/zod-config.ts").read_text()
    assert "jitless: true" in zod_config


def test_static_seo_pages_migrated_to_next():
    """The former static SEO pages (assets/seo/*.html) are migrated to Next.js
    routes — there is now a SINGLE SEO content source (the Next app), and Caddy
    no longer serves any static page from /srv/seo. The self-hosted brand fonts
    + /fonts/* handler remain (brand assets)."""
    seo_html = sorted((ROOT / "assets/seo").glob("*.html"))
    assert not seo_html, (
        "static SEO html should be migrated to Next.js routes, but found: "
        f"{[p.name for p in seo_html]}"
    )

    caddyfile = (ROOT / "Caddyfile").read_text()
    # No static SEO handles remain (robots/sitemap/pages all served by Next).
    assert "root * /srv/seo" not in caddyfile, "Caddy still serves a static /srv/seo page"
    # Brand fonts are still self-hosted + served by Caddy.
    assert "handle /fonts/*" in caddyfile, "Caddy /fonts/* handler missing"
    for font in (
        "assets/brand/fonts/instrument-serif-regular.woff2",
        "assets/brand/fonts/instrument-serif-italic.woff2",
    ):
        assert (ROOT / font).exists(), f"missing committed font file: {font}"
