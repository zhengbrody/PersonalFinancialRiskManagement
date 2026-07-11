import { NextResponse } from "next/server";

/**
 * Permanent 301 redirect for the retired /demo page → the canonical
 * /demo-risk-check. We keep exactly ONE demo page; /demo is dropped from the
 * sitemap.
 *
 * Build the target against the PUBLIC host. Behind Caddy, `request.url` reflects
 * the internal bind address (0.0.0.0:3000), which would produce a broken
 * Location; Caddy forwards the real host as `x-forwarded-host` / `-proto`.
 */
export function GET(request: Request) {
  const host = request.headers.get("x-forwarded-host") || "mindmarket.app";
  const proto = request.headers.get("x-forwarded-proto") || "https";
  return NextResponse.redirect(`${proto}://${host}/demo-risk-check`, 301);
}
