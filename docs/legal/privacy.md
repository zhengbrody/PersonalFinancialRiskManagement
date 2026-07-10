# Privacy Policy

_Last updated: 2026-07-10_

This privacy policy explains how MindMarket AI (mindmarket.app) handles data
during the beta preview period. Every statement here corresponds to behavior
implemented in the product — export and deletion are self-service, and the
analytics filters described below are enforced in code.

> The canonical, always-current copy of this policy is served in-app at
> `/legal/privacy` (source: `frontend/src/lib/legal-content.ts`). This file
> mirrors it.

## What we collect

**Account data** (when you sign up via Supabase Auth):
- Email address and account UUID
- Hashed password (or OAuth identity if you sign in with Google)
- Optional display name; account timestamps

**Portfolio data** (only what you enter or import):
- Tickers, share counts, optional cost basis, option-contract details
- Cash balance, margin loan, contributed capital, portfolio names
- Daily snapshots of your computed Health Score and risk metrics (drives the
  "what changed" view and, only if you opt in, the weekly digest)

**Usage and AI telemetry:**
- Per-feature usage events with timestamps (fair-use limits during the beta)
- AI token counts, model, cost, latency, and a one-way hash of inputs — we do
  not store your prompt text in telemetry

**Diagnostics:**
- Error reports (stack traces and request metadata; never request bodies)
  via Sentry when something breaks — plus in-app feedback messages you choose
  to send (message text + account id)
- Product analytics via PostHog, keyed to your account UUID ONLY — a
  code-enforced filter strips email, tickers, holdings, amounts, and prompt
  text before any event leaves your browser
- IP address and browser user-agent in server/CDN logs, for security

We do **not** collect: real name, address, phone, social security number,
brokerage account numbers, or any banking credentials. We never connect to
your brokerage.

## Where your portfolio data goes

- Risk math (VaR, stress tests, scores) runs on our own servers —
  deterministic Python, no third party involved.
- Market-data providers receive ONLY ticker symbols we look up — never your
  identity, email, or account.
- When you use AI features (Copilot, AI explanations, research verdicts),
  your question plus the computed metrics and holdings context needed to
  answer are sent to the configured LLM provider (DeepSeek or Anthropic).
  These requests are governed by the provider's API terms.
- The weekly digest email (opt-in only) sends your email address and your own
  score summary to our email provider for delivery.

## What we do NOT do

- We do not sell or rent your portfolio holdings or contact info.
- We do not share your data with advertisers.
- We do not send your email, tickers, dollar amounts, or prompts to our
  analytics provider — identification is by account UUID only.
- We do not subscribe you to any marketing or digest email by default —
  email beyond transactional auth flows is explicit opt-in.

## Subprocessors

We rely on these providers:

| Provider | Purpose | Personal / portfolio data involved |
|---|---|---|
| Supabase (US) | Authentication + Postgres database | Account + portfolio data |
| Amazon Web Services (US) | Application hosting | Traffic; data at rest on our instance |
| Cloudflare | DNS, CDN, security proxy | Traffic metadata incl. IPs |
| PostHog (US) | Product analytics | Account UUID + filtered funnel events only |
| Sentry | Error tracking + in-app feedback | Stack traces, request metadata (never request bodies — disabled in code); feedback message text attributed by account id |
| DeepSeek / Anthropic | LLM inference for AI features | Your questions + computed portfolio context |
| Resend | Weekly digest email delivery | Email + digest content, only if you opt in |
| Massive / Financial Modeling Prep / Yahoo Finance | Market prices + fundamentals | By-ticker only; no account identity |
| FRED / US Treasury / SEC EDGAR | Public macro + filings data | No personal data sent |

## Retention, export, and deletion

- **Export:** Portfolios page → "Export CSV / JSON" on any portfolio. The
  file is generated in your browser from data already loaded — no export
  request touches our servers or any third party.
- **Deletion:** Settings → Danger zone → type the confirmation phrase. This
  immediately deletes your auth account and cascades your profile,
  portfolios, score history, usage records, and email preferences.
- **Backups:** encrypted database backups are retained for up to 90 days;
  deleted data disappears from them as they rotate.
- **Weekly digest:** OFF by default. You can opt in from Settings, and every
  email carries a one-click unsubscribe that works without logging in.

## Your rights

You can, self-service:
- Export your portfolios (CSV or JSON) from the Portfolios page
- Delete your account and all associated data from Settings
- Email contact@mindmarket.app for any other data request

## Changes to this policy

We will post any changes here with an updated "Last updated" date.

## Contact

contact@mindmarket.app
