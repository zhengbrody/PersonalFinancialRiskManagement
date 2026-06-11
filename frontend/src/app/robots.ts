// NOTE: in production Caddy serves /robots.txt and /sitemap.xml from
// assets/seo/ (see Caddyfile), which SHADOWS these Next routes. Keep the
// two in sync when adding public pages — this file is what local dev and
// any non-Caddy deployment will serve.
import type { MetadataRoute } from "next";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://mindmarket.app";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: ["/", "/pricing", "/score", "/markets"],
        disallow: [
          "/api/",
          "/admin",
          "/copilot",
          "/institutions",
          "/legacy/",
          "/login",
          "/portfolios",
          "/quant",
          "/research",
          "/risk",
          "/scenarios",
          "/settings",
          "/signup",
        ],
      },
    ],
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  };
}
