/**
 * Single source of truth for the migrated SEO landing pages (formerly the
 * Caddy-served assets/seo/*.html). Each entry drives BOTH the page render
 * (<SeoLanding/>) and its sitemap row, so canonical URL, title, description,
 * the single H1, and lastmod live in exactly one place.
 *
 * `lastmod` is a FIXED content date (NOT build time) — bump it only when a
 * page's content actually changes.
 */

export type SeoSection =
  | { kind: "prose"; h2?: string; body: string[] }
  | { kind: "bullets"; h2?: string; items: string[] } // items may be "Label: description"
  | { kind: "cards"; h2?: string; cards: { title: string; body: string }[] }
  | { kind: "metrics"; items: { label: string; value: string }[] }
  | { kind: "table"; h2?: string; headers: [string, string]; rows: [string, string][] }
  | { kind: "related"; h2: string; links: { label: string; href: string }[] };

export type SeoPage = {
  path: string; // canonical URL path (unchanged from the static file)
  title: string;
  description: string;
  eyebrow: string;
  h1: string;
  lead: string[];
  sections: SeoSection[];
  cta: { label: string; href: string };
  crossLink?: { label: string; href: string }; // e.g. product → learn guide (intent dedupe)
  disclaimer: string;
  priority: number;
  changeFrequency: "monthly" | "weekly";
  lastmod: string; // YYYY-MM-DD, fixed
};

const DISCLAIMER = "Educational and research use only. MindMarket AI is not investment advice.";
const DEMO = "/demo-risk-check";

export const SEO_PAGES: SeoPage[] = [
  {
    path: "/portfolio-risk-management",
    title: "Portfolio Risk Management Software for Investors | MindMarket",
    description:
      "Portfolio risk management software for individual investors: prioritize risk, analyze VaR and drivers, run stress tests, save risk plans, and review changes over time.",
    eyebrow: "Portfolio risk management",
    h1: "Portfolio risk management software for individual investors",
    lead: [
      "MindMarket helps investors move beyond simple gain and loss tracking. It combines quantitative risk analytics with a repeatable workflow for deciding what to inspect, test, save, and review.",
      "Create a portfolio, add holdings or import a supported CSV, review priorities in Today, move through Analyze, and ask grounded Copilot questions about exposure, downside scenarios, diversification, and next research steps.",
    ],
    sections: [
      {
        kind: "cards",
        cards: [
          {
            title: "Today action center",
            body: "Start with the portfolio risks, alerts, and saved decisions that deserve attention now.",
          },
          {
            title: "Unified Analyze workspace",
            body: "Review Health Score, drivers, stress tests, an action plan, and history without switching among disconnected reports.",
          },
          {
            title: "Research, tests, and plans",
            body: "Turn a source-backed research question into a hypothetical test and save the decision for later review.",
          },
        ],
      },
      {
        kind: "prose",
        h2: "Who it is for",
        body: [
          "MindMarket AI is designed for individual investors who manage multiple stocks, ETFs, crypto positions, or concentrated holdings and want a clearer view of downside risk before making allocation decisions.",
        ],
      },
      {
        kind: "related",
        h2: "Related portfolio risk topics",
        links: [
          { label: "AI portfolio analysis for investors", href: "/ai-portfolio-analysis" },
          { label: "Portfolio VaR and stress testing", href: "/portfolio-var-stress-testing" },
          { label: "Margin risk calculator", href: "/margin-risk-calculator" },
          { label: "Portfolio stress test", href: "/portfolio-stress-test" },
          { label: "About MindMarket AI", href: "/about" },
        ],
      },
    ],
    cta: { label: "Analyze your portfolio", href: DEMO },
    crossLink: {
      label: "New to portfolio risk? Read the guide →",
      href: "/learn/portfolio-risk-management",
    },
    disclaimer:
      "MindMarket AI is for education and research only. It does not provide investment, tax, legal, or financial advice.",
    priority: 0.9,
    changeFrequency: "monthly",
    lastmod: "2026-07-15",
  },
  {
    path: "/ai-portfolio-analysis",
    title: "AI Portfolio Analysis for Investors | MindMarket AI",
    description:
      "Use portfolio-aware AI to explain risk drivers, market context, ticker exposure, concentration, score changes, and downside scenarios from traceable evidence.",
    eyebrow: "AI portfolio analysis",
    h1: "AI portfolio analysis grounded in risk metrics and market data",
    lead: [
      "MindMarket combines deterministic portfolio analytics with a Copilot so investors can ask better questions about allocation, concentration, downside risk, and market conditions.",
      "Instead of returning a generic chatbot answer, the Copilot uses the active portfolio, computed metrics, market context, and data-confidence status; it cites tools and lowers conviction when critical evidence is missing.",
    ],
    sections: [
      {
        kind: "bullets",
        h2: "What the AI can help explain",
        items: [
          "Which holdings contribute most to portfolio risk.",
          "Whether the portfolio is concentrated by ticker, sector, or factor exposure.",
          "How drawdown, VaR, CVaR, and stress tests change the risk picture.",
          "Which data is available, current, stale, missing, or supplied by a fallback source.",
          "What research questions an investor may want to investigate next.",
        ],
      },
      {
        kind: "prose",
        h2: "Built for investment research, not trade signals",
        body: [
          "The product is designed as a research and risk-assessment tool. AI output can be incomplete or wrong, and market data can be delayed or unavailable. Treat all AI analysis as educational context, not investment advice.",
        ],
      },
      {
        kind: "related",
        h2: "Related topics",
        links: [
          {
            label: "Personal portfolio risk management software",
            href: "/portfolio-risk-management",
          },
          { label: "Portfolio VaR and stress testing", href: "/portfolio-var-stress-testing" },
          { label: "About MindMarket AI", href: "/about" },
        ],
      },
    ],
    cta: { label: "Try AI portfolio analysis", href: DEMO },
    disclaimer: DISCLAIMER,
    priority: 0.85,
    changeFrequency: "monthly",
    lastmod: "2026-07-15",
  },
  {
    path: "/portfolio-var-stress-testing",
    title: "Portfolio VaR and Stress Testing Tool | MindMarket AI",
    description:
      "MindMarket AI helps investors review portfolio VaR, CVaR, drawdown, stress tests, factor exposure, and downside risk with AI-assisted explanations.",
    eyebrow: "VaR and stress testing",
    h1: "Portfolio VaR and stress testing for individual investors",
    lead: [
      "MindMarket AI helps investors estimate portfolio downside risk using quantitative measures such as value at risk, conditional value at risk, drawdown, volatility, factor exposure, and scenario stress testing.",
      "A portfolio can look healthy when markets are calm but still carry hidden exposure to a sector, mega-cap stock, rate shock, or correlated selloff. Stress testing helps make those risks visible before they become realized losses.",
    ],
    sections: [
      {
        kind: "bullets",
        h2: "Risk metrics covered",
        items: [
          "Value at Risk (VaR) and Conditional Value at Risk (CVaR).",
          "Maximum drawdown and volatility context.",
          "Factor exposure, sector exposure, and ticker concentration.",
          "Portfolio scenario analysis for market, sector, and downside shocks.",
          "AI explanations that connect the numbers to portfolio-level risk questions.",
        ],
      },
      {
        kind: "related",
        h2: "Related topics",
        links: [
          {
            label: "Personal portfolio risk management software",
            href: "/portfolio-risk-management",
          },
          { label: "AI portfolio analysis for investors", href: "/ai-portfolio-analysis" },
          { label: "About MindMarket AI", href: "/about" },
        ],
      },
    ],
    cta: { label: "Run a VaR and stress test", href: DEMO },
    disclaimer:
      "MindMarket AI is for educational and research use only and does not provide investment advice.",
    priority: 0.85,
    changeFrequency: "monthly",
    lastmod: "2026-07-15",
  },
  {
    path: "/personal-portfolio-risk-analysis",
    title: "Personal Portfolio Risk Analysis | MindMarket AI",
    description:
      "Personal portfolio risk analysis for investors who want VaR, CVaR, drawdown, stress testing, concentration risk, margin risk, and AI summaries.",
    eyebrow: "Portfolio risk analysis",
    h1: "Personal portfolio risk analysis for individual investors",
    lead: [
      "A brokerage account can show performance and buying power, but it usually does not explain which positions drive downside risk. MindMarket AI turns a holdings list into a risk dashboard with VaR, CVaR, drawdown, concentration, margin exposure, and AI commentary.",
    ],
    sections: [
      {
        kind: "bullets",
        h2: "What the analysis answers",
        items: [
          "How much could the portfolio lose in a normal downside window?",
          "Which holdings contribute most to VaR and stress loss?",
          "How much leverage is embedded in the current allocation?",
          "What changed since the last analysis?",
        ],
      },
      {
        kind: "prose",
        h2: "How MindMarket AI helps",
        body: [
          "The platform combines quantitative analytics with AI summaries so investors can move from raw numbers to a short list of risks to inspect first.",
        ],
      },
      {
        kind: "related",
        h2: "Related pages",
        links: [
          {
            label: "Personal portfolio risk management software",
            href: "/portfolio-risk-management",
          },
          { label: "Margin risk calculator", href: "/margin-risk-calculator" },
          { label: "Sample portfolio risk report", href: "/sample-risk-report" },
        ],
      },
    ],
    cta: { label: "Analyze a portfolio", href: DEMO },
    disclaimer: DISCLAIMER,
    priority: 0.85,
    changeFrequency: "monthly",
    lastmod: "2026-07-15",
  },
  {
    path: "/margin-risk-calculator",
    title: "Margin Risk Calculator for Stock Portfolios | MindMarket AI",
    description:
      "Use MindMarket AI as a margin risk calculator to review net equity, margin loan, leverage, buying power context, stress loss, and margin call distance.",
    eyebrow: "Margin risk",
    h1: "Margin risk calculator for investors using leverage",
    lead: [
      "Buying power is not always cash. If it comes from margin availability, a portfolio can appear flexible while net equity is still exposed to a faster drawdown. MindMarket AI separates contributed capital, cash balance, margin loan, total long exposure, and net equity.",
    ],
    sections: [
      {
        kind: "bullets",
        h2: "Metrics to review",
        items: [
          "Total long exposure: market value of positions.",
          "Margin loan: borrowed balance currently supporting positions.",
          "Net equity: portfolio value after subtracting margin debt.",
          "Leverage: total long exposure divided by net equity.",
          "Stress loss: estimated portfolio response to a market shock.",
        ],
      },
      {
        kind: "prose",
        h2: "Why it matters",
        body: [
          "Leverage can make a moderate market decline become a much larger equity drawdown. The product helps investors see whether new trades are being funded by unused cash or by additional margin capacity.",
        ],
      },
      {
        kind: "related",
        h2: "Related pages",
        links: [
          { label: "Robinhood margin risk analysis", href: "/robinhood-margin-risk" },
          { label: "Portfolio stress test", href: "/portfolio-stress-test" },
          { label: "Try a sample portfolio demo", href: DEMO },
        ],
      },
    ],
    cta: { label: "Check margin risk", href: DEMO },
    disclaimer: DISCLAIMER,
    priority: 0.85,
    changeFrequency: "monthly",
    lastmod: "2026-07-15",
  },
  {
    path: "/portfolio-stress-test",
    title: "Portfolio Stress Test Tool | MindMarket AI",
    description:
      "Run portfolio stress tests for market shocks, drawdown, margin pressure, sector concentration, volatility, VaR, and CVaR with MindMarket AI.",
    eyebrow: "Stress testing",
    h1: "Portfolio stress testing before the market tests you",
    lead: [
      "A portfolio stress test asks a practical question: what happens if the market moves against your current allocation? MindMarket AI estimates downside scenarios and shows whether the biggest risk comes from market beta, concentration, leverage, or specific holdings.",
    ],
    sections: [
      {
        kind: "bullets",
        h2: "Stress tests included in the workflow",
        items: [
          "Market shock scenarios for broad selloffs.",
          "Asset-level stress loss based on beta and portfolio weights.",
          "Margin pressure from leveraged exposure.",
          "Historical drawdown and volatility context.",
        ],
      },
      {
        kind: "prose",
        h2: "Stress testing plus AI context",
        body: [
          "The AI risk analyst can explain which holdings matter most, what metrics are stale or missing, and how to turn stress-test results into a research plan.",
        ],
      },
      {
        kind: "related",
        h2: "Related pages",
        links: [
          { label: "Portfolio VaR and stress testing", href: "/portfolio-var-stress-testing" },
          {
            label: "Stock portfolio concentration risk",
            href: "/stock-portfolio-concentration-risk",
          },
          { label: "Sample portfolio risk report", href: "/sample-risk-report" },
        ],
      },
    ],
    cta: { label: "Run a stress test", href: DEMO },
    disclaimer: DISCLAIMER,
    priority: 0.85,
    changeFrequency: "monthly",
    lastmod: "2026-07-15",
  },
  {
    path: "/stock-portfolio-concentration-risk",
    title: "Stock Portfolio Concentration Risk | MindMarket AI",
    description:
      "Measure stock portfolio concentration risk with top-position weights, sector exposure, component VaR, stress testing, drawdown, and AI risk summaries.",
    eyebrow: "Concentration risk",
    h1: "Measure whether a few stocks dominate your portfolio risk",
    lead: [
      "Concentration risk is not only about position size. A holding can be a large source of risk because it has high volatility, high beta, strong correlation with other holdings, or exposure to the same sector theme.",
    ],
    sections: [
      {
        kind: "bullets",
        h2: "MindMarket AI highlights",
        items: [
          "Top positions by portfolio weight and market value.",
          "Component VaR so users can see which names drive downside risk.",
          "Sector and factor exposure to detect hidden clustering.",
          "AI action cards that turn concentration metrics into review steps.",
        ],
      },
      {
        kind: "prose",
        h2: "Why concentration can be hidden",
        body: [
          "A portfolio can look diversified by ticker count while still being exposed to one market theme, such as mega-cap technology, semiconductor beta, crypto risk, or levered ETFs. Risk analysis should inspect both weights and correlations.",
        ],
      },
      {
        kind: "related",
        h2: "Related pages",
        links: [
          { label: "Personal portfolio risk analysis", href: "/personal-portfolio-risk-analysis" },
          { label: "Portfolio stress test", href: "/portfolio-stress-test" },
          { label: "Try the sample portfolio demo", href: DEMO },
        ],
      },
    ],
    cta: { label: "Check concentration risk", href: DEMO },
    disclaimer: DISCLAIMER,
    priority: 0.8,
    changeFrequency: "monthly",
    lastmod: "2026-07-15",
  },
  {
    path: "/robinhood-margin-risk",
    title: "Robinhood Margin Risk Analysis | MindMarket AI",
    description:
      "Understand Robinhood-style buying power, cash, margin total, margin used, net equity, leverage, and stress loss with MindMarket AI portfolio analytics.",
    eyebrow: "Robinhood margin",
    h1: "Analyze Robinhood margin risk beyond buying power",
    lead: [
      "Robinhood buying power can include unused margin capacity. If cash is zero but buying power is positive, that buying power is not the same as spare cash in a portfolio risk model. MindMarket AI helps users enter cash, margin loan, contributed capital, and holdings separately.",
    ],
    sections: [
      {
        kind: "bullets",
        h2: "How to map brokerage fields",
        items: [
          "Cash: real cash balance shown by the broker.",
          "Margin used: borrowed amount currently financing positions.",
          "Buying power: capacity to buy, which may include margin availability.",
          "Net equity: holdings plus cash minus margin loan.",
        ],
      },
      {
        kind: "prose",
        h2: "Why this matters for risk",
        body: [
          "Entering margin buying power as cash can understate leverage and overstate downside cushion. A cleaner model separates deployable cash from borrowing capacity, then stress tests the portfolio against market losses.",
        ],
      },
      {
        kind: "related",
        h2: "Related pages",
        links: [
          { label: "Margin risk calculator", href: "/margin-risk-calculator" },
          { label: "Sample portfolio risk report", href: "/sample-risk-report" },
          { label: "Portfolio risk management software", href: "/portfolio-risk-management" },
        ],
      },
    ],
    cta: { label: "Analyze margin risk", href: DEMO },
    disclaimer: DISCLAIMER,
    priority: 0.8,
    changeFrequency: "monthly",
    lastmod: "2026-07-15",
  },
  {
    path: "/sample-risk-report",
    title: "Sample Portfolio Risk Workflow | MindMarket",
    description:
      "Follow a sample portfolio from risk snapshot to top drivers, stress loss, action cards, and a hypothetical test that can be saved for review.",
    eyebrow: "Sample workflow",
    h1: "Portfolio risk workflow example",
    lead: [
      "This sample starts with a risk snapshot, then shows how MindMarket turns capital base, leverage, VaR, stress loss, and top positions into a testable action and a decision that can be reviewed later.",
    ],
    sections: [
      {
        kind: "metrics",
        items: [
          { label: "Net equity", value: "$27,300" },
          { label: "Total long", value: "$44,500" },
          { label: "Margin loan", value: "$17,200" },
          { label: "Leverage", value: "1.63x" },
          { label: "VaR 95", value: "-4.5%" },
          { label: "Stress loss", value: "-12.8%" },
        ],
      },
      {
        kind: "table",
        h2: "Top risk drivers",
        headers: ["Driver", "Why it matters"],
        rows: [
          [
            "Margin amplification",
            "A market decline can reduce net equity faster than the gross portfolio moves.",
          ],
          [
            "Top-name concentration",
            "Large weights in a few tickers can dominate VaR and drawdown.",
          ],
          [
            "Short inverse ETF exposure",
            "Levered and inverse funds can behave differently across volatile sessions.",
          ],
        ],
      },
      {
        kind: "cards",
        h2: "Sample action cards",
        cards: [
          {
            title: "Check margin buffer first",
            body: "Confirm whether buying power is unused margin capacity or real cash.",
          },
          {
            title: "Rank top VaR contributors",
            body: "Focus review on holdings that drive portfolio loss, not only holdings with the largest gain.",
          },
          {
            title: "Stress test before adding exposure",
            body: "Compare current leverage against a -10% market shock.",
          },
        ],
      },
    ],
    cta: { label: "Run the sample workflow", href: DEMO },
    disclaimer: "Educational and research use only. This sample is not investment advice.",
    priority: 0.8,
    changeFrequency: "monthly",
    lastmod: "2026-07-15",
  },
];

export const SEO_BY_PATH: Record<string, SeoPage> = Object.fromEntries(
  SEO_PAGES.map((p) => [p.path, p]),
);
