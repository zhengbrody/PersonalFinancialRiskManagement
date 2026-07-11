# Acquisition & activation analytics funnel

Privacy-safe product analytics on PostHog. The rule is simple: **we measure the
journey, never the money.** No ticker, share count, portfolio id, email, prompt,
dollar amount, or holding name ever reaches PostHog.

## How privacy is enforced (defense in depth)

1. **Typed event names** — `track()` accepts only members of `ANALYTICS_EVENTS`
   (`src/lib/analytics-events.ts`). An ad-hoc string is a compile error, so the
   event set is closed and auditable.
2. **Property deny-list** — `redactProps` (`src/lib/analytics.ts`) drops any
   property whose key contains investment content (`ticker`, `symbol`, `holding`,
   `prompt`, `email`, `amount`, `usd`, `price`, `portfolio_id`, …). So even a
   careless `track("x", { ticker })` leaks nothing.
3. **`holdings_band` allowlist** — a portfolio's size is reported as a coarse
   band, never an exact count. `holdingsBand(n)` → `"0" | "1-5" | "6-10" | "11+"`.
   (`holdings_band` contains the substring `holding`, so it's an explicit
   allowlist exception; the exact keys `holdings` / `holdings_count` are dropped.)
4. **URL sanitizer** — a PostHog `sanitize_properties` hook strips query + hash
   from the library-attached `$current_url` / `$referrer` (so an OAuth `code` or a
   `?q=<prompt>` deep link never rides along) and templates path UUIDs to `:id`.
5. **UTM allowlist** — only `utm_source`, `utm_medium`, `utm_campaign`,
   `utm_content` are ever read from the query (`readUtm`). OAuth `code`,
   `access_token`, `ticker`, `utm_term`, and any other key are never read.
6. **Dev/test no-op** — analytics only initialize when
   `NODE_ENV === "production"`; every emitter early-returns otherwise, so dev and
   tests never touch the project.

There are **no hard-coded industry benchmarks** anywhere in the analytics code —
funnel targets belong in the PostHog dashboard, judged against our own data.

## First-touch attribution

The first visit's allowlisted UTM is saved to `sessionStorage`
(`captureFirstTouchUtm`, key `mm_first_utm`, first-touch only) and attached to
`signup_completed` and to the PostHog identity (`getFirstTouchUtm`), so a signup
can be attributed to the campaign that brought the user in — with campaign labels
only, no PII.

## The funnel (17 events)

| # | Event | When | Properties (all privacy-safe) |
|---|-------|------|-------------------------------|
| 1 | `landing_viewed` | Anonymous marketing landing mounts | — |
| 2 | `hero_cta_clicked` | Hero CTA clicked | `target: "demo" \| "signup"` |
| 3 | `demo_started` | `/demo-risk-check` mounts | `source` |
| 4 | `demo_interacted` | First interaction in the sample cockpit | — |
| 5 | `public_check_started` | No-signup risk check begun | — |
| 6 | `public_check_completed` | No-signup risk check produced a result | `holdings_band` |
| 7 | `signup_started` | Signup attempt begins (email or Google) | `method: "email" \| "google"` |
| 8 | `signup_completed` | Account created | `method`, `needs_confirmation`, first-touch `utm_*` |
| 9 | `signup_failed` | Signup failed | `method`, `error_category` (category only, never the message) |
| 10 | `onboarding_started` | Dashboard onboarding guide shown (no portfolio yet) | — |
| 11 | `csv_imported` | Broker CSV mapped into the form | `holdings_band` |
| 12 | `portfolio_created` | Portfolio saved | `holdings_band` |
| 13 | `first_score_completed` | First Health Score for this browser | — |
| 14 | `risk_report_opened` | Risk Report viewed | — |
| 15 | `copilot_message_sent` | Copilot message sent | `variant` (never the message text) |
| 16 | `digest_opted_in` | Weekly digest turned on | — |
| 17 | `returned_7d` | Known visitor returns after ≥7 days | `away_bucket: "7-30d" \| "30d+"` |

`signup_failed` records only an `error_category`
(`already_registered` / `weak_password` / `invalid_email` / `rate_limited` /
`network` / `oauth` / `unknown`) — never the raw error message, which can echo
user input.

## Recommended funnels (build these in PostHog)

- **Acquisition → activation (anonymous):**
  `landing_viewed` → `hero_cta_clicked` → `demo_started` → `demo_interacted` →
  `signup_started` → `signup_completed`.
- **No-signup value → signup:**
  `public_check_started` → `public_check_completed` → `signup_started` →
  `signup_completed`.
- **Activation (post-signup):**
  `signup_completed` → `onboarding_started` → (`csv_imported` →)
  `portfolio_created` → `first_score_completed` → `risk_report_opened` /
  `copilot_message_sent`.
- **Retention:** `first_score_completed` → `digest_opted_in` → `returned_7d`.

Break each funnel down by first-touch `utm_source` / `utm_campaign` for
channel-level conversion, and by `method` for signup.

## Other product events (also typed)

Kept for feature-usage analysis, all through the same typed `track()` +
deny-list: `signup_oauth_started`, `research_started`, `copilot_handoff_clicked`,
`quant_tab_changed`, `risk_tab_changed`, `scenario_shock_selected`,
`score_change_window`, `score_viewed`, `report_export_clicked`,
`upgrade_clicked`, `whatif_loaded_holdings`, `whatif_run`, `demo_stress_toggled`,
`share_card_created`, `public_check_csv_imported`, `public_check_signup_cta`,
`risk_diagnosis_viewed`, `copilot_opened`, `copilot_followup_clicked`,
`copilot_ask`, `sticky_cta_clicked`, `markets_sentiment_viewed`.

## Where things live

- `src/lib/analytics-events.ts` — the event catalog + `holdingsBand` + UTM helpers.
- `src/lib/analytics.ts` — `track` / `identifyUser`, the deny-list + `holdings_band`
  allowlist, the URL sanitizer, first-touch UTM storage, the 7-day return check.
- `src/components/analytics-provider.tsx` — init, identify/reset on auth,
  per-navigation `$pageview` (query stripped), first-touch UTM capture, `returned_7d`.
- Tests: `analytics-events.test.ts` (bands, UTM allowlist, property filter,
  first-touch storage, catalog), `analytics.test.ts` + `analytics-boundary.test.ts`
  (redaction + wire-level guarantees).
