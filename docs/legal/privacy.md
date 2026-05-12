# Privacy Policy

_Last updated: 2026-05-09_

This privacy policy explains how MindMarket AI (mindmarket.app) handles data
during the beta preview period. It may be updated before a broader public
launch.

## What we collect

**Account data** (when you sign up via Supabase Auth):
- Email address
- Hashed password (or OAuth identity if you sign in with Google)
- Account creation timestamp

**Portfolio data** (only what you enter):
- Tickers, share counts, optional cost basis
- Margin loan dollar amount
- Portfolio names you assign

**Usage data** (for billing / quota enforcement):
- Number of AI analyses + chat messages per month
- Plan tier (free / basic / pro)
- Timestamps of usage events

**Inferred data**:
- IP address, browser user-agent (collected by hosting provider for security)

We do **not** collect: real name, address, phone, social security number,
brokerage account numbers, or any banking credentials.

## What we do with it
- Operate the service: store your portfolios, render your dashboards, run
  analyses you request.
- Bill / enforce quota: track usage events to apply free/basic/pro caps.
- Improve the product: aggregate, anonymized usage statistics. We do not sell
  user data.

## What we do NOT do
- We do not sell or rent your portfolio holdings or contact info.
- We do not share your data with advertisers.
- We do not connect to your brokerage accounts; we only see what you type
  into the portfolio editor.

## Third parties
We rely on these subprocessors:
- **Supabase** — auth + Postgres database
- **Anthropic / DeepSeek / OpenAI** — LLM inference (we send the prompts you
  generate; we do NOT send your auth credentials)
- **Yahoo Finance, Financial Modeling Prep, SEC EDGAR** — market data lookups
  (these are by-ticker only; the providers do not see your portfolio)
- **AWS / Cloudflare** — hosting + DNS

## Your rights
You can:
- Export your portfolios via the Portfolios page
- Delete your account, which removes profile + portfolios + usage events
- Email contact@mindmarket.app for any data request

## Changes to this policy
We will post any changes here with an updated "Last updated" date.

## Contact
contact@mindmarket.app
