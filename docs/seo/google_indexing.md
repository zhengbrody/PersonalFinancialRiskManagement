# Google Indexing Runbook

Goal: make `mindmarket.app` discoverable for queries such as `MindMarket AI`,
`mindmarket`, and `mind market`.

## What the app serves

- `https://mindmarket.app/robots.txt`
- `https://mindmarket.app/sitemap.xml` (served by Next.js — single source)
- `https://mindmarket.app/` — the Next.js marketing landing (SSR, crawlable)
- `https://mindmarket.app/about`, `/product`, `/learn`, `/resources`, `/risk-today`

The `google-site-verification` token is now emitted **site-wide** via the Next
root metadata (`frontend/src/app/layout.tsx` → `verification.google`), so the
HTML-tag method verifies the homepage URL — not only `/about.html` as before.

## Verify ownership (do this once)

**Recommended: DNS verification (whole domain, survives any page change).**

1. In Search Console, add a **Domain** property: `mindmarket.app`.
2. It gives a `google-site-verification=…` **TXT** record.
3. Add that TXT record in **Cloudflare → DNS** (Cloudflare is the resolver now):
   Type `TXT`, Name `@`, Content the full `google-site-verification=…` string.
4. Back in Search Console, click **Verify**. This covers `http`+`https` and all
   subdomains at once.

Backup: **HTML tag** (URL-prefix property `https://mindmarket.app/`) — already
wired site-wide via the layout metadata above, so it verifies without any extra
deploy once the property is added.

## Search Console steps (after verifying)

1. Go to **Sitemaps** and submit:

   ```text
   https://mindmarket.app/sitemap.xml
   ```

2. Go to **URL inspection** → Request indexing for the priority pages:

   ```text
   https://mindmarket.app/
   https://mindmarket.app/product
   https://mindmarket.app/risk-today
   https://mindmarket.app/resources
   https://mindmarket.app/learn
   ```

## Product-education pages (added 2026-06-15)

The pre-login education layer is now crawlable SSR (Googlebot sees full text,
not a JS shell). All are in the single Next.js `sitemap.ts` (the former static
`assets/seo/sitemap.xml` and its Caddy handle were removed):

- `https://mindmarket.app/product` — four-pillar overview + `SoftwareApplication`
  JSON-LD.
- `https://mindmarket.app/learn` — hub + `ItemList` JSON-LD.
- `https://mindmarket.app/learn/<slug>` — 10 topic guides, each with `FAQPage`
  + `BreadcrumbList` JSON-LD. Slugs: `portfolio-risk-management`,
  `var-cvar-explained`, `factor-exposure`, `stress-testing`, `margin-risk`,
  `options-risk`, `stock-research`, `sharpe-ratio-explained`,
  `maximum-drawdown`, `diversification-correlation`.
- `https://mindmarket.app/resources` — an internal-linking hub connecting the
  `/learn/*` guides AND the standalone keyword pages (now Next.js routes,
  formerly `assets/seo/*.html`), which previously had no inbound internal links.
- `https://mindmarket.app/risk-today` — daily-refreshing market risk-state
  (SSR prose + live desk).

Internal linking: the marketing landing links to `/product` + `/learn`;
`/resources` links every guide + keyword page; the footer links
`/product`/`/learn`/`/resources`/`/markets`/`/risk-today`/`/demo`; the
authenticated Risk Report + Research dossier deep-link into `/learn/<slug>`
via `<LearnHint>`; each topic cross-links related topics. So crawlers reach
every page from `/`.

### Verification checklist (do after each deploy that adds/edits public pages)

1. `curl -s https://mindmarket.app/sitemap.xml | grep -c "<loc>"` — expect the
   full URL count (currently 33: core + 10 learn guides + `/resources` +
   `/risk-today` + 3 legal).
2. `curl -s https://mindmarket.app/learn | grep -o "application/ld+json"` —
   confirms JSON-LD shipped (not stripped by a build).
3. `curl -s https://mindmarket.app/learn/var-cvar-explained | grep -c "FAQPage"`
   — expect ≥1.
4. View-source a topic page → the prose is in the initial HTML (SSR), not only
   in a hydration payload.
5. OG card: `curl -sI https://mindmarket.app/og.jpg` → `200` + `image/jpeg`;
   the topic/product/learn metadata reference `summary_large_image`.

### Search Console — submit the new pages

1. **Sitemaps** → confirm `https://mindmarket.app/sitemap.xml` is still
   submitted (it now contains the new URLs — no re-submit needed, but
   "Resubmit" forces a re-crawl).
2. **URL inspection** → Request indexing for:

   ```text
   https://mindmarket.app/product
   https://mindmarket.app/learn
   https://mindmarket.app/learn/portfolio-risk-management
   https://mindmarket.app/learn/var-cvar-explained
   ```

3. **Rich Results Test** (search.google.com/test/rich-results) → paste a
   `/learn/<slug>` URL → expect FAQ + Breadcrumb to validate.

## Expectations

Google indexing is not instant. Verification can complete immediately, but
search results can take days or weeks. Ranking for the generic phrase
`mind market` is not guaranteed; exact-brand queries like `MindMarket AI` and
`mindmarket.app` should appear first. The `/learn/*` guides target
informational long-tail queries (e.g. "what is CVaR", "portfolio factor
exposure") and are the main organic-discovery surface.

