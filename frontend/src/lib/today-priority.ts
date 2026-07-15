/**
 * Today's deterministic priority engine. Given the user's state, it picks the
 * ONE primary action + up to two secondary items — pure logic, NEVER an LLM.
 * The order is fixed (most-blocking first) so the home surface always points at
 * the single most useful next step.
 */

export type TodayInputs = {
  hasPortfolio: boolean;
  hasHoldings: boolean;
  /** Score data quality is low / stale — metrics can't be trusted yet. */
  dataStale: boolean;
  /** Risk plans past their review_at (not resolved/archived). */
  dueReviewCount: number;
  /** A high-severity proactive insight (headline only — no content here). */
  hasMaterialInsight: boolean;
  /** Health score dropped meaningfully since the last snapshot. */
  scoreDropped: boolean;
  /** journey.first_stress_test_at is set. */
  hasStressTest: boolean;
  /** journey.first_plan_at is set. */
  hasPlan: boolean;
  /** The active portfolio id, for deep-links (null when none). */
  activePortfolioId: string | null;
};

export type TodayActionKind =
  | "create_portfolio"
  | "add_holdings"
  | "fix_data"
  | "review_plan"
  | "investigate_insight"
  | "explain_change"
  | "first_stress_test"
  | "first_plan"
  | "review_changes";

export type TodayAction = {
  kind: TodayActionKind;
  title: string;
  description: string;
  href: string;
  cta: string;
};

export function computePrimaryAction(i: TodayInputs): TodayAction {
  const pf = i.activePortfolioId;
  if (!i.hasPortfolio) {
    return {
      kind: "create_portfolio",
      title: "Add your first portfolio",
      description: "Enter your holdings to get a health score and risk analysis.",
      href: "/portfolios/new",
      cta: "Create a portfolio",
    };
  }
  if (!i.hasHoldings) {
    return {
      kind: "add_holdings",
      title: "Add holdings to your portfolio",
      description: "Your portfolio has no positions yet — add them to analyze risk.",
      href: pf ? `/portfolios/${pf}/edit` : "/portfolios",
      cta: "Add holdings",
    };
  }
  if (i.dataStale) {
    return {
      kind: "fix_data",
      title: "Your data needs attention",
      description:
        "Some prices are missing or the history is thin, so the metrics can't be trusted yet. Check what's missing.",
      href: "/analyze?view=overview",
      cta: "Review data coverage",
    };
  }
  if (i.dueReviewCount > 0) {
    return {
      kind: "review_plan",
      title: `Review ${i.dueReviewCount} risk plan${i.dueReviewCount === 1 ? "" : "s"}`,
      description: "You set a plan to revisit — compare it to where your portfolio is now.",
      href: "/analyze?view=plan",
      cta: "Review plans",
    };
  }
  if (i.hasMaterialInsight) {
    return {
      kind: "investigate_insight",
      title: "A material risk to look at",
      description: "Something meaningful changed or stands out in your portfolio. See what and why.",
      href: "/analyze?view=drivers",
      cta: "Investigate",
    };
  }
  if (i.scoreDropped) {
    return {
      kind: "explain_change",
      title: "Your health score dropped",
      description: "See exactly what moved it — market vs your own changes — since your last visit.",
      href: "/analyze?view=history",
      cta: "Explain the change",
    };
  }
  if (!i.hasStressTest) {
    return {
      kind: "first_stress_test",
      title: "Run your first stress test",
      description: "See how your portfolio would hold up in a downturn — a −20% shock or a real crisis.",
      href: "/analyze?view=stress",
      cta: "Run a stress test",
    };
  }
  if (!i.hasPlan) {
    return {
      kind: "first_plan",
      title: "Save your first risk plan",
      description: "Try a what-if change and save it as a plan to revisit later — no trades, just analysis.",
      href: "/analyze?view=stress",
      cta: "Try a what-if",
    };
  }
  return {
    kind: "review_changes",
    title: "Review what changed",
    description: "You're set up — check your latest trends and what moved since last time.",
    href: "/analyze?view=history",
    cta: "See what changed",
  };
}

/** Up to two secondary items — the next-best steps that aren't the primary,
 * skipping any that would duplicate it. Deterministic, deep-linked. */
export function computeSecondary(i: TodayInputs, primary: TodayActionKind): TodayAction[] {
  const out: TodayAction[] = [];
  const push = (a: TodayAction) => {
    if (a.kind !== primary && out.length < 2) out.push(a);
  };
  if (i.hasPortfolio && i.hasHoldings && !i.dataStale) {
    if (i.dueReviewCount === 0 && i.hasStressTest) {
      push({
        kind: "review_plan",
        title: "Saved plans",
        description: "Revisit or add a risk plan.",
        href: "/analyze?view=plan",
        cta: "Open plans",
      });
    }
    // Don't offer a Drivers secondary when the PRIMARY already sends there
    // (investigate_insight → drivers) — no duplicate destination.
    if (primary !== "investigate_insight") {
      push({
        kind: "review_changes",
        title: "Drivers of your risk",
        description: "What's contributing most to your risk right now.",
        href: "/analyze?view=drivers",
        cta: "See drivers",
      });
    }
    if (!i.hasStressTest) {
      push({
        kind: "first_stress_test",
        title: "Stress test",
        description: "See downside scenarios on your book.",
        href: "/analyze?view=stress",
        cta: "Open stress test",
      });
    }
  }
  return out;
}

/** The onboarding journey checklist — ordered steps + which is next. Hidden
 * once every step is done. */
export type JourneyStep = { key: string; label: string; done: boolean; href: string };

export function journeySteps(i: {
  hasPortfolio: boolean;
  hasScore: boolean;
  hasDriverView: boolean;
  hasStressTest: boolean;
  hasPlan: boolean;
}): { steps: JourneyStep[]; nextIndex: number; allDone: boolean } {
  const steps: JourneyStep[] = [
    { key: "portfolio", label: "Add your portfolio", done: i.hasPortfolio, href: "/portfolios/new" },
    { key: "score", label: "Get your health score", done: i.hasScore, href: "/analyze?view=overview" },
    { key: "drivers", label: "See your risk drivers", done: i.hasDriverView, href: "/analyze?view=drivers" },
    { key: "stress", label: "Run a stress test", done: i.hasStressTest, href: "/analyze?view=stress" },
    // A FIRST plan is saved from a what-if in the Stress stage (the Plan stage
    // only lists existing plans) — send the user where they can actually create one.
    { key: "plan", label: "Save a risk plan", done: i.hasPlan, href: "/analyze?view=stress" },
  ];
  const nextIndex = steps.findIndex((s) => !s.done);
  return { steps, nextIndex, allDone: nextIndex === -1 };
}
