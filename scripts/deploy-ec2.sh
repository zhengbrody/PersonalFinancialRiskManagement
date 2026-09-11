#!/usr/bin/env bash
# scripts/deploy-ec2.sh — one-command pull-only deploy (run ON the EC2 box).
#
#   ./scripts/deploy-ec2.sh                # deploy :latest
#   ./scripts/deploy-ec2.sh sha-<full40>   # deploy/ROLL BACK to a pinned build
#
# Encodes the exact runbook from docs/aws/ci-image-deploy.md so the guardrails
# are code, not memory:
#   * pull-only + --no-build  — an on-box build OOMs the t3.micro (2 outages)
#   * --no-deps + explicit service names — never touches caddy (owned by
#     compose.aws.yml in the same project)
#   * NEVER --remove-orphans — it would delete the caddy container
# Rollback = run this with the previous sha tag (see GHCR package versions or
# `git log --oneline` + the sha-<full-commit-sha> tag convention).
set -euo pipefail

TAG="${1:-latest}"
# Export ONCE so BOTH pull and up interpolate the same tag — prefixing only
# the pull line would silently `up` whatever :latest is cached locally.
export MM_IMAGE_TAG="$TAG"

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "== Preflight (RAM/disk — pull-only, but headroom still matters) =="
free -m || true
df -h / || true

echo "== Sync repo (compose/Caddyfile/assets ride git, not images) =="
git pull --ff-only origin main
if [ "$TAG" != "latest" ]; then
  echo "NOTE: images are pinned to ${TAG}, but compose/Caddyfile/assets were"
  echo "      just fast-forwarded to origin/main. A CONFIG regression needs a"
  echo "      git revert on main (the boot unit resets to origin/main too) —"
  echo "      an image pin alone does not roll config back."
fi

echo "== Pull + swap app containers (tag: ${MM_IMAGE_TAG}) =="
docker compose -f compose.split.yml pull backend frontend
docker compose -f compose.split.yml up -d --no-deps --no-build backend frontend

# The Caddyfile is a SINGLE-FILE bind mount, so the running container holds the
# old inode: a git pull updates the file on disk and changes nothing that is
# serving. It has to be recreated, and validating first matters because an
# invalid Caddyfile crash-loops the container (that is how the site once went
# 521 after a reboot). Validation runs with the REAL certs mounted because the
# committed Caddyfile pins `tls /srv/tls/origin.pem` and validation loads it.
#
# The trigger is a MARKER holding the hash of the last SUCCESSFULLY-applied
# file, not a before/after diff across the pull. A diff only sees the change on
# the run that performs the pull, so if a later step fails (an image that isn't
# built yet, say) the new config sits on disk while caddy serves the old one --
# and every re-run then decides "unchanged" and skips it forever.
CADDY_MARKER=".caddy-applied"
CADDY_NOW="$(sha256sum Caddyfile | cut -d' ' -f1)"
CADDY_APPLIED="$(cat "$CADDY_MARKER" 2>/dev/null || echo none)"
if [ "$CADDY_NOW" != "$CADDY_APPLIED" ]; then
  echo "== Caddyfile not yet applied (${CADDY_APPLIED:0:12} -> ${CADDY_NOW:0:12}): validate, then recreate =="
  docker run --rm \
    -v "$PWD/Caddyfile:/etc/caddy/Caddyfile:ro" \
    -v /srv/tls:/srv/tls:ro \
    -e SITE_HOST="${SITE_HOST:-mindmarket.app}" \
    caddy:2.11-alpine caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
  docker compose -f compose.aws.yml up -d --force-recreate --no-deps caddy
  echo "$CADDY_NOW" > "$CADDY_MARKER"
  echo "   (recreated; a lone 'no OCSP stapling ... Origin CA' warning is expected)"
else
  echo "== Caddyfile already applied — not touching caddy =="
fi

echo "== Reclaim disk (unused images; volumes/containers untouched) =="
docker image prune -af

echo "== Status =="
docker compose -f compose.split.yml ps

echo "== Smoke (through Cloudflare; retries cover container start-up) =="
# The recreated backend takes ~30-60s to become healthy (heavy imports on the
# t3.micro) — a single immediate curl would false-fail a good deploy under
# set -e. Retry up to 6× (10s apart) before declaring failure.
SITE="${SITE_HOST:-mindmarket.app}"
smoke() {
  local path="$1" attempt
  for attempt in 1 2 3 4 5 6; do
    if curl -fsS -m 15 -o /dev/null "https://${SITE}${path}"; then
      echo "GET ${path} -> OK (attempt ${attempt})"
      return 0
    fi
    echo "GET ${path} not ready (attempt ${attempt}/6) — waiting 10s"
    sleep 10
  done
  echo "GET ${path} FAILED after 6 attempts" >&2
  return 1
}
smoke "/"
smoke "/api/v1/health"
smoke "/api/v1/macro/regime"
# Deep readiness is reported but NON-FATAL here: a Supabase blip must not
# fail an otherwise-good container swap. The GH deploy workflow's verify job
# (and the external monitor) treat deep degradation as a real failure.
deep_code=$(curl -s -o /dev/null -w "%{http_code}" -m 20 "https://${SITE}/api/v1/health?deep=1" || echo 000)
if [ "$deep_code" = "200" ]; then
  echo "GET /api/v1/health?deep=1 -> OK"
else
  echo "WARN: deep readiness returned ${deep_code} — product may be degraded (Supabase/config); investigate, deploy itself is complete."
fi

echo "Deploy OK (${MM_IMAGE_TAG})"
