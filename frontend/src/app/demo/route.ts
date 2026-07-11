import { NextResponse } from "next/server";

/**
 * Permanent 301 redirect for the retired /demo page → the canonical
 * /demo-risk-check. We keep exactly ONE demo page; /demo is dropped from the
 * sitemap. (Caddy used to serve assets/seo/demo.html here — that handle is
 * removed so this route takes over.)
 */
export function GET(request: Request) {
  return NextResponse.redirect(new URL("/demo-risk-check", request.url), 301);
}
