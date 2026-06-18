/**
 * Legal copy for /legal/[doc] — Terms of Service, Privacy Policy, Financial
 * Disclaimer. Plain typed data so the routes render server-side (SSR/SEO-
 * friendly, no markdown dependency — keeps the "no unnecessary libraries" rule).
 * The canonical source is docs/legal/*.md; keep the two in sync. MindMarket is
 * an educational product — nothing here is investment advice.
 */

export type LegalBlock =
  | { kind: "text"; text: string }
  | { kind: "lead"; label: string; text?: string }
  | { kind: "list"; items: string[] };

export type LegalSection = { heading: string; blocks: LegalBlock[] };

export type LegalDoc = {
  slug: "terms" | "privacy" | "disclaimer";
  /** Short label for footer + breadcrumb. */
  nav: string;
  /** H1 on the page. */
  title: string;
  /** <title> — unique per page. */
  metaTitle: string;
  /** meta description. */
  description: string;
  lastUpdated: string;
  intro: string;
  sections: LegalSection[];
  contactEmail: string;
};

const CONTACT = "contact@mindmarket.app";

const terms: LegalDoc = {
  slug: "terms",
  nav: "Terms",
  title: "Terms of Service",
  metaTitle: "Terms of Service — MindMarket",
  description:
    "The beta terms that govern use of MindMarket AI: eligibility, acceptable use, liability, and governing law.",
  lastUpdated: "2026-05-09",
  intro:
    "These beta terms govern use of MindMarket AI (mindmarket.app). They may be updated before a broader public launch.",
  sections: [
    {
      heading: "1. Acceptance",
      blocks: [
        {
          kind: "text",
          text: "By creating an account or using MindMarket AI, you agree to these terms and to the Privacy Policy and Financial Disclaimer.",
        },
      ],
    },
    {
      heading: "2. Eligibility",
      blocks: [
        {
          kind: "text",
          text: "You must be at least 18 years old. You must not use the service in any jurisdiction where doing so violates local law.",
        },
      ],
    },
    {
      heading: "3. The service",
      blocks: [
        {
          kind: "text",
          text: "MindMarket AI provides portfolio risk analytics, AI-generated commentary, options education, and market data tools. The service is provided “as is”, without warranty of any kind, express or implied.",
        },
      ],
    },
    {
      heading: "4. Account responsibility",
      blocks: [
        {
          kind: "text",
          text: `You are responsible for keeping your password secret and for all activity under your account. Notify us immediately at ${CONTACT} if you suspect unauthorized access.`,
        },
      ],
    },
    {
      heading: "5. Beta access",
      blocks: [
        {
          kind: "text",
          text: "MindMarket AI is currently a free educational beta. There are no charges, and no payment information is collected. If paid plans are introduced later, separate billing terms will be presented for your review before any charge applies.",
        },
      ],
    },
    {
      heading: "6. Acceptable use",
      blocks: [
        { kind: "lead", label: "You agree NOT to:" },
        {
          kind: "list",
          items: [
            "Reverse engineer, decompile, or scrape the service en masse",
            "Resell access without written permission",
            "Upload portfolios that aren’t yours, or impersonate another user",
            "Use the service to give regulated investment advice to third parties",
            "Abuse the AI quota (e.g. via automation that bypasses rate limits)",
          ],
        },
      ],
    },
    {
      heading: "7. Intellectual property",
      blocks: [
        {
          kind: "text",
          text: "The MindMarket AI platform, code, design, and AI prompts are owned by the operator. You retain ownership of any portfolio data or notes you upload. You grant us a limited license to process that data solely to provide the service to you.",
        },
      ],
    },
    {
      heading: "8. Disclaimer of advice",
      blocks: [
        {
          kind: "text",
          text: "Nothing on the service is investment advice. See the Financial Disclaimer for the full text.",
        },
      ],
    },
    {
      heading: "9. Limitation of liability",
      blocks: [
        {
          kind: "text",
          text: "To the maximum extent permitted by law, the operator’s total liability for any claim arising out of or related to the service is limited to the greater of (a) $100 USD or (b) the amount you paid us in the 12 months preceding the claim.",
        },
        {
          kind: "text",
          text: "We are not liable for indirect, incidental, special, or consequential damages, including lost profits or trading losses, even if advised of the possibility of such damages.",
        },
      ],
    },
    {
      heading: "10. Indemnification",
      blocks: [
        {
          kind: "text",
          text: "You agree to indemnify the operator against any third-party claim arising from your misuse of the service or your violation of these terms.",
        },
      ],
    },
    {
      heading: "11. Termination",
      blocks: [
        {
          kind: "text",
          text: "We may suspend or terminate accounts for violation of these terms, suspected fraud, or security issues. You may delete your account at any time.",
        },
      ],
    },
    {
      heading: "12. Governing law",
      blocks: [
        {
          kind: "text",
          text: "These terms are governed by the laws of the State of California, USA, with exclusive venue in the state and federal courts located in San Francisco County, California.",
        },
      ],
    },
    {
      heading: "13. Changes",
      blocks: [
        {
          kind: "text",
          text: "We may update these terms. Material changes will be announced in-app and via email. Continued use after the effective date constitutes acceptance.",
        },
      ],
    },
  ],
  contactEmail: CONTACT,
};

const privacy: LegalDoc = {
  slug: "privacy",
  nav: "Privacy",
  title: "Privacy Policy",
  metaTitle: "Privacy Policy — MindMarket",
  description:
    "How MindMarket AI handles your data: what we collect, what we do (and don’t) do with it, our subprocessors, and your rights.",
  lastUpdated: "2026-05-09",
  intro:
    "This privacy policy explains how MindMarket AI (mindmarket.app) handles data during the beta preview period. It may be updated before a broader public launch.",
  sections: [
    {
      heading: "What we collect",
      blocks: [
        { kind: "lead", label: "Account data", text: " (when you sign up via Supabase Auth):" },
        {
          kind: "list",
          items: [
            "Email address",
            "Hashed password (or OAuth identity if you sign in with Google)",
            "Account creation timestamp",
          ],
        },
        { kind: "lead", label: "Portfolio data", text: " (only what you enter):" },
        {
          kind: "list",
          items: [
            "Tickers, share counts, optional cost basis",
            "Margin loan dollar amount",
            "Portfolio names you assign",
          ],
        },
        { kind: "lead", label: "Usage data", text: " (for fair-use limits during the beta):" },
        {
          kind: "list",
          items: [
            "Number of AI analyses + chat messages per month",
            "Usage tier",
            "Timestamps of usage events",
          ],
        },
        { kind: "lead", label: "Inferred data", text: ":" },
        {
          kind: "list",
          items: ["IP address, browser user-agent (collected by hosting provider for security)"],
        },
        {
          kind: "text",
          text: "We do not collect: real name, address, phone, social security number, brokerage account numbers, or any banking credentials.",
        },
      ],
    },
    {
      heading: "What we do with it",
      blocks: [
        {
          kind: "list",
          items: [
            "Operate the service: store your portfolios, render your dashboards, run analyses you request.",
            "Apply usage limits: track usage events to apply fair-use limits during the beta.",
            "Improve the product: aggregate, anonymized usage statistics. We do not sell user data.",
          ],
        },
      ],
    },
    {
      heading: "What we do NOT do",
      blocks: [
        {
          kind: "list",
          items: [
            "We do not sell or rent your portfolio holdings or contact info.",
            "We do not share your data with advertisers.",
            "We do not connect to your brokerage accounts; we only see what you type into the portfolio editor.",
          ],
        },
      ],
    },
    {
      heading: "Third parties",
      blocks: [
        { kind: "lead", label: "We rely on these subprocessors:" },
        {
          kind: "list",
          items: [
            "Supabase — auth + Postgres database",
            "Anthropic / DeepSeek / OpenAI — LLM inference (we send the prompts you generate; we do NOT send your auth credentials)",
            "Yahoo Finance, Financial Modeling Prep, SEC EDGAR — market data lookups (these are by-ticker only; the providers do not see your portfolio)",
            "AWS / Cloudflare — hosting + DNS",
          ],
        },
      ],
    },
    {
      heading: "Your rights",
      blocks: [
        { kind: "lead", label: "You can:" },
        {
          kind: "list",
          items: [
            "Export your portfolios via the Portfolios page",
            "Delete your account, which removes profile + portfolios + usage events",
            `Email ${CONTACT} for any data request`,
          ],
        },
      ],
    },
    {
      heading: "Changes to this policy",
      blocks: [
        {
          kind: "text",
          text: "We will post any changes here with an updated “Last updated” date.",
        },
      ],
    },
  ],
  contactEmail: CONTACT,
};

const disclaimer: LegalDoc = {
  slug: "disclaimer",
  nav: "Disclaimer",
  title: "Financial Disclaimer",
  metaTitle: "Financial Disclaimer — MindMarket",
  description:
    "MindMarket AI is an educational and research tool. Nothing on the site is investment advice or a recommendation to buy or sell any security.",
  lastUpdated: "2026-05-09",
  intro:
    "MindMarket AI is an educational and research tool. Nothing on this site is investment advice, a recommendation to buy or sell any security, or a solicitation of any kind.",
  sections: [
    {
      heading: "Not investment advice",
      blocks: [
        {
          kind: "text",
          text: "The analytics, AI-generated commentary, scenario simulations, options education, and “trade ideas” surfaced anywhere in this product are provided for informational purposes only. They do not take into account your specific financial situation, objectives, or risk tolerance.",
        },
        {
          kind: "text",
          text: "You should consult a licensed financial advisor before making any investment decision. The operators of MindMarket AI are not licensed broker-dealers, registered investment advisors, or financial planners.",
        },
      ],
    },
    {
      heading: "No warranty on data",
      blocks: [
        {
          kind: "text",
          text: "Market data is sourced from third-party providers (Yahoo Finance, Financial Modeling Prep, SEC EDGAR, public RSS feeds, etc.). We make no representation that the data is accurate, complete, current, or free of errors. Risk metrics (VaR, CVaR, betas, factor exposures, options Greeks) are model outputs and carry estimation error.",
        },
        {
          kind: "text",
          text: "Past performance is not indicative of future results. All forecasts and simulations are statistical estimates, not predictions.",
        },
      ],
    },
    {
      heading: "AI-generated content",
      blocks: [
        {
          kind: "text",
          text: "LLM-powered summaries (Claude, DeepSeek, etc.) may produce inaccurate, incomplete, or hallucinated content. Always verify any specific claim (earnings figures, analyst targets, news events) against the underlying primary source before acting on it.",
        },
      ],
    },
    {
      heading: "Your responsibility",
      blocks: [
        {
          kind: "text",
          text: "You are solely responsible for your investment decisions and any losses you may incur. By using this site, you acknowledge that you have read and agree to this disclaimer.",
        },
      ],
    },
  ],
  contactEmail: CONTACT,
};

export const LEGAL_DOCS: LegalDoc[] = [terms, privacy, disclaimer];
export const LEGAL_BY_SLUG: Record<string, LegalDoc> = Object.fromEntries(
  LEGAL_DOCS.map((d) => [d.slug, d]),
);
export const LEGAL_SLUGS = LEGAL_DOCS.map((d) => d.slug);
