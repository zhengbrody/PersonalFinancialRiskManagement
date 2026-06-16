# Google Indexing Runbook

Goal: make `mindmarket.app` discoverable for queries such as `MindMarket AI`,
`mindmarket`, and `mind market`.

## What the app serves

- `https://mindmarket.app/robots.txt`
- `https://mindmarket.app/sitemap.xml`
- `https://mindmarket.app/about`
- `https://mindmarket.app/googlecpW5HG50AaWNMEfTxdGBF6JxeviA-0QFaHDYS0xw_N8.html`

`/about` is a static crawlable page with the exact phrases `MindMarket AI`,
`Mind Market`, and `portfolio risk analytics`. The Streamlit app remains at `/`.

## Search Console steps

1. Open Google Search Console.
2. Select the `mindmarket.app` property.
3. Confirm ownership is verified.
4. Go to **Sitemaps**.
5. Submit:

   ```text
   https://mindmarket.app/sitemap.xml
   ```

6. Go to **URL inspection** and request indexing for:

   ```text
   https://mindmarket.app/
   https://mindmarket.app/about
   ```

## Product-education pages (added 2026-06-15)

The pre-login education layer is now crawlable SSR (Googlebot sees full text,
not a JS shell). All are in both sitemaps (`assets/seo/sitemap.xml` — served by
Caddy — and the Next `sitemap.ts` mirror):

- `https://mindmarket.app/product` — four-pillar overview + `SoftwareApplication`
  JSON-LD.
- `https://mindmarket.app/learn` — hub + `ItemList` JSON-LD.
- `https://mindmarket.app/learn/<slug>` — 7 topic guides, each with `FAQPage`
  + `BreadcrumbList` JSON-LD. Slugs: `portfolio-risk-management`,
  `var-cvar-explained`, `factor-exposure`, `stress-testing`, `margin-risk`,
  `options-risk`, `stock-research`.

Internal linking: the marketing landing links to `/product` + `/learn`; the
authenticated Risk Report + Research dossier deep-link into `/learn/<slug>`
via `<LearnHint>`; each topic cross-links related topics. So crawlers reach
every page from `/`.

### Verification checklist (do after each deploy that adds/edits public pages)

1. `curl -s https://mindmarket.app/sitemap.xml | grep -c "<loc>"` — expect the
   full URL count (currently 24: 15 core + 9 product/learn entries).
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

