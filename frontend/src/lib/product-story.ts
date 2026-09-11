/**
 * Public product narrative for MindMarket's Portfolio Risk OS.
 *
 * Marketing pages import this data instead of maintaining separate feature
 * lists. Keeping the workflow in one place prevents the public site from
 * drifting away from the signed-in Today / Analyze / Research / Copilot IA.
 */

export const PRODUCT_POSITIONING = {
  name: "Portfolio Risk OS",
  headline: "Understand your risk before your next move.",
  description:
    "See what drives your portfolio’s risk, test a change, and understand the trade-offs—without changing your actual holdings.",
} as const;

export const RISK_WORKFLOW = [
  {
    key: "today",
    label: "Today",
    title: "See what changed",
    body: "Start with a short, deterministic priority list for the active portfolio — not another wall of charts.",
  },
  {
    key: "analyze",
    label: "Analyze",
    title: "Locate the risk",
    body: "Move through Overview, Drivers, Stress Test, Action Plan, and History without losing portfolio context.",
  },
  {
    key: "test",
    label: "Test",
    title: "Model a change",
    body: "Test additions, reductions or replacements in the stock/ETF portion of your portfolio. This Research sandbox excludes cash and option legs; real holdings stay unchanged.",
  },
  {
    key: "plan",
    label: "Plan",
    title: "Save the decision",
    body: "Save supported scenarios as risk plans. Copilot comparison drafts require an available save action and your confirmation; they preserve the original calculation.",
  },
  {
    key: "review",
    label: "Review",
    title: "Return when it matters",
    body: "Reopen saved plans, inspect recorded score history, and manage alerts. Reviews depend on comparable metrics; saving a plan does not start automatic monitoring.",
  },
] as const;

export const PRODUCT_SURFACES = [
  {
    key: "today",
    title: "Today action center",
    tag: "Prioritized, not noisy",
    body: "A prioritized view of available risks, alerts and plan reviews for your active portfolio when you open the workspace.",
    href: "/product#workflow",
  },
  {
    key: "analyze",
    title: "Unified Analyze workspace",
    tag: "One connected analysis",
    body: "Health Score, drivers, stress tests, action planning, and history live in one staged workspace rather than scattered reports.",
    href: "/product#analyze",
  },
  {
    key: "research",
    title: "Research to Test",
    tag: "Ideas become scenarios",
    body: "Move from ticker research into a stock/ETF-only what-if. Compare that portion of your portfolio, not the risk of a full account containing cash and options.",
    href: "/product#research-to-test",
  },
  {
    key: "plans",
    title: "Risk plans and alert lifecycle",
    tag: "Decisions persist",
    body: "Save a scenario, review it later, and mark alerts seen, snoozed, or resolved without losing the underlying evidence.",
    href: "/product#plans",
  },
  {
    key: "copilot",
    title: "Portfolio-aware Copilot",
    tag: "Computed evidence, checked explanations",
    body: "Ask about available portfolio evidence or test a supported stock/ETF reduction. Inspect sources and data limits; AI explanations can still be wrong.",
    href: "/product#copilot",
  },
] as const;

/** Match the separate signed-in workflows; do not market one as the other.
 * Evidence and release caveats: docs/marketing/public-experience.md.
 */
export const COMPARISON_CAPABILITIES = [
  {
    key: "research",
    title: "Research: test the stock/ETF portion",
    body: "Try adding, increasing, reducing or replacing a position in the equity-only sandbox.",
    limitation: "Cash and option legs are excluded. These results are not a full-account risk comparison.",
  },
  {
    key: "copilot",
    title: "Copilot: compare a held stock/ETF reduction",
    body: "Enter a USD amount and choose to keep the hypothetical proceeds as cash or repay margin. Supported option legs remain unchanged.",
    limitation: "Supported US-listed, USD-priced holdings only. Equity-only comparisons use historical risk metrics; accounts with options use instantaneous stresses, not historical account VaR or volatility. Missing or ambiguous inputs can prevent a comparison.",
  },
  {
    key: "save",
    title: "Save a captured comparison when available",
    body: "Confirm an eligible result to keep its original calculation as a draft plan. The account revision and capture age are checked before a new save.",
    limitation: "A new save requires a capture within 15 minutes. Saving does not refresh quotes, execute a trade or start automatic monitoring. Later reviews require comparable data.",
  },
] as const;

export const PRODUCT_FAQS = [
  {
    question: "What does MindMarket help me do?",
    answer:
      "MindMarket helps you review portfolio priorities, trace risk drivers, run what-if tests, save risk plans, and revisit decisions as the portfolio or market changes.",
  },
  {
    question: "Do tests change my real holdings?",
    answer:
      "No. Research-to-Test models the stock/ETF portion only. Copilot can compare a supported stock/ETF reduction with keeping the portfolio unchanged. Neither places trades or changes your saved holdings.",
  },
  {
    question: "How does Copilot use my portfolio data?",
    answer:
      "Risk figures come from calculation services. Copilot explains the available evidence with output checks and data-quality limits. AI explanations can still be wrong; inspect the evidence and assumptions before relying on a result.",
  },
  {
    question: "Is the sample based on live market data?",
    answer: "No. The interactive sample uses fictional holdings and fixed sensitivities to explain a hypothetical change. It is not the full risk engine, a return forecast, or a maximum-loss calculation. The assumptions are available beside the results.",
  },
  {
    question: "Are all options strategies and changes supported?",
    answer: "No. Support depends on the analysis, contract details and available data. The current Copilot comparison tests reductions in supported held stocks or ETFs; it does not edit option legs or automatically optimize every strategy.",
  },
  {
    question: "Does saving a plan start an autonomous agent?",
    answer: "No. A saved plan is a record for you to revisit. Copilot comparison drafts preserve a captured calculation, not continuously refreshed prices. Saving does not launch background monitoring, automatic optimization or trade execution.",
  },
] as const;
