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
smoke "/api/v1/macro/regime"

echo "Deploy OK (${MM_IMAGE_TAG})"
