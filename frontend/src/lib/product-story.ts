/**
 * Public product narrative for MindMarket's Portfolio Risk OS.
 *
 * Marketing pages import this data instead of maintaining separate feature
 * lists. Keeping the workflow in one place prevents the public site from
 * drifting away from the signed-in Today / Analyze / Research / Copilot IA.
 */

export const PRODUCT_POSITIONING = {
  name: "Portfolio Risk OS",
  headline: "Know what changed. Test what matters. Keep a risk plan.",
  description:
    "MindMarket is a portfolio risk operating system for individual investors: review today's priorities, trace risk in Analyze, test changes without touching holdings, save a plan, and revisit it when conditions change.",
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
    body: "Send a research idea into a what-if test and compare the before-and-after risk — real holdings are never changed.",
  },
  {
    key: "plan",
    label: "Plan",
    title: "Save the decision",
    body: "Keep the scenario, rationale, and review state together as a risk plan instead of exporting a forgotten report.",
  },
  {
    key: "review",
    label: "Review",
    title: "Return when it matters",
    body: "Alerts, saved plans, and score history show what deserves another look as the portfolio or market changes.",
  },
] as const;

export const PRODUCT_SURFACES = [
  {
    key: "today",
    title: "Today action center",
    tag: "Prioritized, not noisy",
    body: "A daily queue of the risks, alerts, and plan reviews that matter most for the active portfolio.",
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
    body: "Move from source-backed ticker research into a portfolio what-if and see the risk impact before saving a plan.",
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
    tag: "Grounded, not improvising",
    body: "Ask why risk changed, inspect exposure, and navigate to the next useful surface with citations and explicit data-confidence limits.",
    href: "/product#copilot",
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
      "No. Research-to-Test and scenario tools re-score a hypothetical portfolio. They do not place trades or mutate the holdings you saved.",
  },
  {
    question: "Does the Copilot invent portfolio numbers?",
    answer:
      "No. Risk figures come from deterministic services. The Copilot explains available evidence, cites its tools, and lowers confidence when important data is missing or stale.",
  },
] as const;
