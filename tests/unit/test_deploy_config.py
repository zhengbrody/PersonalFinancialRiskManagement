import re
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


def _env_names_read_by_backend_config() -> set[str]:
    """Every environment variable ``backend/app/core/config.py`` actually reads."""
    text = (ROOT / "backend" / "app" / "core" / "config.py").read_text(encoding="utf-8")
    names: set[str] = set()
    for pattern in (
        r'_env\w*\(\s*"([A-Z][A-Z0-9_]+)"',
        r'os\.environ(?:\.get)?\(\s*"([A-Z][A-Z0-9_]+)"',
        r'os\.getenv\(\s*"([A-Z][A-Z0-9_]+)"',
    ):
        names |= set(re.findall(pattern, text))
    return names


def test_split_compose_forwards_every_variable_the_backend_reads():
    """A setting the code reads but compose does not forward is invisible.

    Values live in the EC2 `.env`; docker compose only injects the variables
    named in the service's `environment:` block. One left out silently stays at
    its default, so the feature looks broken with nothing in the logs -- the
    MASSIVE_API_KEY class of bug, which has now happened three times
    (MASSIVE_API_KEY, the two comparison flags, and a whole documented
    owner-activation procedure for the API-balance card whose env path was
    never wired).

    This is DERIVED from config.py rather than a hand-kept list, because a
    hand-kept list is exactly what went stale each time. Adding a setting and
    forgetting compose now fails here instead of in production.
    """
    compose = (ROOT / "compose.split.yml").read_text(encoding="utf-8")
    backend_block = compose.split("backend:", 1)[1].split("frontend:", 1)[0]
    forwarded = set(re.findall(r"-\s+([A-Z][A-Z0-9_]+)=", backend_block))

    missing = sorted(_env_names_read_by_backend_config() - forwarded)
    assert not missing, (
        "read by backend/app/core/config.py but not forwarded to the backend "
        f"container, so setting them in the EC2 .env does nothing: {missing}"
    )


def test_image_build_passes_every_public_build_arg_the_frontend_declares():
    """A NEXT_PUBLIC_* value is baked at BUILD time, not read at runtime.

    If the Dockerfile declares the ARG but the workflow never passes it, the
    published image is frozen at the default and the owner cannot turn the
    feature on no matter what they set -- which is where
    NEXT_PUBLIC_PUBLIC_RISK_CHECK was.
    """
    dockerfile = (ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    declared = set(re.findall(r"^ARG\s+(NEXT_PUBLIC_[A-Z0-9_]+)", dockerfile, re.M))

    workflow = (ROOT / ".github" / "workflows" / "build-images.yml").read_text(encoding="utf-8")
    passed = set(re.findall(r"(NEXT_PUBLIC_[A-Z0-9_]+)=", workflow))

    missing = sorted(declared - passed)
    assert not missing, (
        "declared as a build ARG but never passed by build-images.yml, so the "
        f"published image is stuck at the default: {missing}"
    )


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


def test_deploy_script_actually_applies_a_changed_caddyfile():
    """A git pull updates the Caddyfile; it does not apply it.

    The Caddyfile is a single-file bind mount, so the running container keeps
    the old inode and a committed change is a silent no-op. This was hit in
    production (the new security headers were absent after the deploy that
    shipped them) and had to be applied by hand. The script must validate --
    an invalid Caddyfile crash-loops the container -- and then recreate.
    """
    script = (ROOT / "scripts" / "deploy-ec2.sh").read_text(encoding="utf-8")

    assert "caddy validate" in script, "must validate before recreating"
    assert (
        "/srv/tls" in script
    ), "validation loads the pinned Origin CA cert; without the mount it fails"
    assert "--force-recreate" in script and "caddy" in script, "must recreate caddy"
    # The trigger must be a MARKER holding the last APPLIED hash. A
    # before/after diff across the git pull only fires on the run that pulls, so
    # any later failure (an image that isn't built yet, say) leaves the new
    # config on disk, caddy serving the old one, and every re-run deciding
    # "unchanged" -- permanently unapplied. Assert the read, the write, and the
    # absence of the diff approach's tell-tale.
    assert 'cat "$CADDY_MARKER"' in script, "must READ the last-applied marker"
    assert (
        'echo "$CADDY_NOW" > "$CADDY_MARKER"' in script
    ), "must WRITE the marker only after a successful recreate"
    assert "sha256sum Caddyfile" in script, "the marker must hash the file itself"
    assert (
        "git rev-parse HEAD:Caddyfile" not in script
    ), "that is the before/after-diff approach this replaced"
    commands = [ln for ln in script.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    assert not any("--remove-orphans" in ln for ln in commands), (
        "--remove-orphans would delete the caddy container (it is owned by the "
        "other compose file) -- the header comment says so; keep it a comment"
    )
