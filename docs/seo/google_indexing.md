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

## Expectations

Google indexing is not instant. Verification can complete immediately, but
search results can take days or weeks. Ranking for the generic phrase
`mind market` is not guaranteed; exact-brand queries like `MindMarket AI` and
`mindmarket.app` should appear first.

