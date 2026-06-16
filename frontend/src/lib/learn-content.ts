/**
 * Content source for the /learn educational hub. Plain data so the route
 * components stay thin and the pages render server-side (SSR/SEO-friendly —
 * Googlebot sees the full text without hydration). Human-written, example-led,
 * educational only — never buy/sell advice.
 */

export type LearnSection = {
  heading: string;
  paragraphs: string[];
  example?: { label: string; body: string };
};

export type LearnFaq = { q: string; a: string };

export type LearnTopic = {
  slug: string;
  /** Card title in the hub + H1 on the page. */
  title: string;
  /** <title> — unique per page. */
  metaTitle: string;
  /** meta description + hub card blurb. */
  description: string;
  eyebrow: string;
  intro: string;
  sections: LearnSection[];
  faqs: LearnFaq[];
  related: string[]; // slugs
};

export const LEARN_TOPICS: LearnTopic[] = [
  {
    slug: "portfolio-risk-management",
    title: "Portfolio risk management for individual investors",
    metaTitle: "Portfolio Risk Management — A Practical Guide for Individual Investors",
    description:
      "What portfolio risk actually is, why ticker count isn't diversification, and how to measure concentration, volatility, and drawdown on your own holdings.",
    eyebrow: "Foundations",
    intro:
      "Most retail portfolios aren't risky because of one bad pick — they're risky because several positions quietly move together. Managing portfolio risk means measuring how your holdings behave as a whole, not one ticker at a time.",
    sections: [
      {
        heading: "Diversification by ticker count is not diversification by risk",
        paragraphs: [
          "Owning 12 names feels diversified. But if eight of them are mega-cap tech, a single rate shock can hit all eight at once — that's one bet wearing twelve costumes.",
          "Real diversification is about the correlation and factor exposure of your holdings, not how many lines are in your account. Two ETFs can overlap 80%; two single stocks in different sectors might still both be high-beta growth.",
        ],
        example: {
          label: "Example",
          body: "NVDA + QQQ + SMH look like three positions, but QQQ and SMH already hold NVDA. Your true Nvidia exposure can be 25–30% of the book even though it shows as one 10% line.",
        },
      },
      {
        heading: "The three things worth measuring first",
        paragraphs: [
          "Concentration: how much of your downside comes from one name. A position can be 10% of value but 30% of risk.",
          "Volatility & beta: how sharply the whole portfolio swings, and how much of that is just 'the market' moving (beta) versus your own picks.",
          "Drawdown: the worst peak-to-trough fall you'd have sat through. A 20% annual return means little if you'd have needed to survive a 45% drop to earn it.",
        ],
      },
      {
        heading: "Risk is only useful relative to your goal",
        paragraphs: [
          "A 25% annual-volatility book is fine for a 25-year-old with a long horizon and reckless for someone drawing income next year. There's no universal 'too risky' — only too risky for your target.",
          "That's why a Health Score compares your actual volatility and beta to a chosen risk preference, instead of declaring a single right answer.",
        ],
      },
    ],
    faqs: [
      {
        q: "How many holdings should I own to be diversified?",
        a: "There's no magic number. What matters is whether your holdings move independently. Ten positions that all behave like the Nasdaq behave like one position. Measuring effective holdings (1 / Herfindahl index) tells you how many independent bets you really have.",
      },
      {
        q: "Is a high return a sign of a good portfolio?",
        a: "Not on its own. A high return earned through a 45% drawdown and 30% volatility may be worse, risk-adjusted, than a steadier 12%. Look at return per unit of risk (Sharpe) and the drawdown you'd have endured.",
      },
      {
        q: "Can I manage portfolio risk without selling anything?",
        a: "Yes — the first step is simply seeing it. Knowing your concentration, beta, and worst-case stress loss changes how you size the next position, even before you touch the current ones.",
      },
    ],
    related: ["var-cvar-explained", "factor-exposure", "stress-testing"],
  },
  {
    slug: "var-cvar-explained",
    title: "VaR and CVaR explained, with a real example",
    metaTitle: "VaR & CVaR Explained — Value at Risk and Expected Shortfall, Simply",
    description:
      "Value at Risk and Conditional VaR in plain English: what a '5% daily VaR of 2%' actually means, and why CVaR captures the tail VaR misses.",
    eyebrow: "Risk metrics",
    intro:
      "Value at Risk (VaR) answers a simple question: on a normal bad day, how much could I lose? Conditional VaR (CVaR) answers the harder one: when it's worse than that, how bad is it on average?",
    sections: [
      {
        heading: "What VaR is — and isn't",
        paragraphs: [
          "A 1-day 95% VaR of 2% means: on about 19 of 20 days, your loss should stay under 2% of the portfolio. It does NOT say the most you can lose is 2% — roughly 1 day in 20, you'd expect to lose more.",
          "VaR is a threshold, not a worst case. Its blind spot is exactly the tail it cuts off.",
        ],
        example: {
          label: "Example",
          body: "On a $50,000 book, a 2% daily 95% VaR ≈ $1,000. That's your 'normal bad day' line. The point of CVaR is to describe the days that breach it.",
        },
      },
      {
        heading: "CVaR sees the tail VaR ignores",
        paragraphs: [
          "Conditional VaR (also called Expected Shortfall) is the average loss on the worst ~5% of days — the days that blow past VaR. If your 95% VaR is 2% but your 95% CVaR is 3.5%, your bad days tend to be much worse than the threshold suggests.",
          "A big gap between VaR and CVaR is a fat-tail warning: your portfolio takes occasional outsized hits.",
        ],
      },
      {
        heading: "How to read them together",
        paragraphs: [
          "VaR sizes the routine downside; CVaR sizes the surprise. Concentrated, high-beta, or options-heavy books usually show a wide VaR-to-CVaR gap.",
          "Backtesting helps too: if your model VaR is breached far more than 5% of days over the last year, your real tails are fatter than the normal-distribution assumption implies.",
        ],
      },
    ],
    faqs: [
      {
        q: "Is a 95% VaR or a 99% VaR better to look at?",
        a: "Neither is 'better' — they answer different questions. 95% describes a typical bad day (~1 in 20); 99% describes a rare one (~1 in 100). Looking at both, plus CVaR, gives a fuller picture of the downside.",
      },
      {
        q: "Why does my VaR change when I add a position?",
        a: "VaR depends on how positions move together, not just each one alone. Adding a holding that's correlated with what you already own can raise VaR more than its size suggests; an uncorrelated one can lower it.",
      },
      {
        q: "Does VaR predict crashes?",
        a: "No. VaR is a statistical summary of normal-regime risk, not a forecast. That's why stress testing — applying a specific −20% or −30% shock — complements it.",
      },
    ],
    related: ["stress-testing", "portfolio-risk-management", "factor-exposure"],
  },
  {
    slug: "factor-exposure",
    title: "Factor exposure and beta: what's really driving your returns",
    metaTitle: "Factor Exposure & Beta Explained — What Drives Your Portfolio",
    description:
      "Beta and factor exposure show how much of your portfolio's movement is the market, growth, value, rates, or gold — not your stock-picking.",
    eyebrow: "Attribution",
    intro:
      "Two portfolios can hold completely different tickers and still rise and fall together — because they share the same underlying factors. Factor exposure shows what your returns are actually made of.",
    sections: [
      {
        heading: "Beta: how much is just the market?",
        paragraphs: [
          "Beta measures how much your portfolio moves with a benchmark. A beta of 1.0 moves in step with the market; 1.4 amplifies it by ~40% in both directions; 0.7 dampens it.",
          "A beta of 1.4 means a −10% market day is, on average, a −14% day for you. High return often just means high beta in a bull market — which reverses in a sell-off.",
        ],
        example: {
          label: "Example",
          body: "A book of NVDA, TSLA, and QQQ might regress to a market beta near 1.3 plus heavy 'growth' and 'tech' factor loadings — so most of its swings are those factors, not idiosyncratic stock picks.",
        },
      },
      {
        heading: "Factors beyond the market",
        paragraphs: [
          "Regressing your returns on factor proxies (large-cap, tech/growth, small-cap, value, gold, long Treasuries) reveals tilts you may not have chosen on purpose.",
          "A portfolio can be unknowingly short duration (hurt by rising rates), long growth, and zero defensive — a combination that feels diversified by ticker but isn't by factor.",
        ],
      },
      {
        heading: "Why it matters for the next trade",
        paragraphs: [
          "If you're already 1.3 beta and growth-tilted, adding another high-beta growth name concentrates the same bet. Knowing your factor map tells you what would actually diversify — often something boring and low-correlation.",
        ],
      },
    ],
    faqs: [
      {
        q: "What's a 'good' beta?",
        a: "It depends on your goal and horizon. Lower beta means smaller market-driven swings; higher beta means bigger ones in both directions. The point is to know your beta and decide if it matches your risk tolerance, not to hit a target number.",
      },
      {
        q: "Can factor exposure be negative?",
        a: "Yes. A negative loading on long Treasuries, for instance, means your portfolio tends to fall when bonds rise — i.e. you're exposed to rate moves. Negative factor betas are common and informative.",
      },
    ],
    related: ["portfolio-risk-management", "var-cvar-explained", "stress-testing"],
  },
  {
    slug: "stress-testing",
    title: "Stress testing your portfolio: beyond the average day",
    metaTitle: "Portfolio Stress Testing Explained — Scenario & Historical Shocks",
    description:
      "Stress testing applies specific shocks (−10%, −20%, −30%, or real crises like 2022 and COVID) to your actual holdings to see who gets hit hardest.",
    eyebrow: "Scenarios",
    intro:
      "Average-day metrics like volatility and VaR describe the routine. Stress testing asks a sharper question: if the market dropped 20% tomorrow — or repeated 2022 — what happens to my specific book, position by position?",
    sections: [
      {
        heading: "Scenario shocks vs historical replay",
        paragraphs: [
          "A scenario shock applies a hypothetical move (say −20%) scaled by each holding's beta, so high-beta names fall more. It's clean and instant.",
          "A historical replay runs your current holdings through a real episode — the 2022 drawdown, the COVID crash, GFC — using what those names (or their proxies) actually did. It captures correlations a simple beta scaling can miss.",
        ],
        example: {
          label: "Example",
          body: "Under a −20% market scenario, a 1.4-beta growth book might project a −28% portfolio loss, with the most-impacted holdings being the highest-beta single names — exactly the ones a 'diversified' ticker list can hide.",
        },
      },
      {
        heading: "Read who gets hit, not just the total",
        paragraphs: [
          "The total projected loss matters, but the ranking of impacted holdings is more actionable: it tells you which positions are doing the damage and whether your 'safe' sleeve actually cushions anything.",
        ],
      },
      {
        heading: "Stress tests complement, not replace, VaR",
        paragraphs: [
          "VaR summarizes normal-regime risk statistically; a stress test is a specific, explainable 'what if'. Use both: VaR for the routine, scenarios for the events you actually worry about.",
        ],
      },
    ],
    faqs: [
      {
        q: "What shock size should I test?",
        a: "Common reference points are −10% (a correction), −20% (a bear-market leg), and −30% (a severe drawdown). Testing a range — plus a real historical crisis — is more informative than a single number.",
      },
      {
        q: "Are stress-test losses guaranteed?",
        a: "No. A stress test is a conditional 'if this move happened' estimate based on betas and history, not a prediction. Actual losses depend on how correlations behave in the real event.",
      },
    ],
    related: ["var-cvar-explained", "factor-exposure", "margin-risk"],
  },
  {
    slug: "margin-risk",
    title: "Margin risk: how leverage changes everything",
    metaTitle: "Margin Risk Explained — Leverage, Margin Calls & Forced Selling",
    description:
      "Margin amplifies both gains and losses and adds a new failure mode: a margin call that forces selling at the worst possible time. How to see your distance to one.",
    eyebrow: "Leverage",
    intro:
      "Margin doesn't just make a portfolio more volatile — it adds a hard floor. Below a maintenance threshold, the broker, not you, decides when to sell. Understanding your margin risk is mostly about knowing how far you are from that line.",
    sections: [
      {
        heading: "Leverage scales risk, not just return",
        paragraphs: [
          "If you're 1.5× levered, a −10% move in your assets is roughly a −15% move in your equity (before borrow costs). Volatility, VaR, and drawdown all scale up by the leverage factor.",
          "The seductive part is the upside scales the same way — which is why leverage feels great until the first real drawdown.",
        ],
        example: {
          label: "Example",
          body: "On $50,000 of assets with a $15,000 margin loan, your net equity is $35,000 and leverage ≈ 1.43×. A −20% asset drop is a −$10,000 hit — about −29% of your equity, not −20%.",
        },
      },
      {
        heading: "The margin call: the real tail risk",
        paragraphs: [
          "Brokers require your equity to stay above a maintenance margin (often ~25–30% of position value). Cross below it and you get a margin call — meet it with cash, or positions get liquidated, frequently near the bottom.",
          "Forced selling crystallizes losses and removes your choice of when to exit. The distance from your current equity to the maintenance line is the number to watch.",
        ],
      },
      {
        heading: "Folding margin into the risk picture",
        paragraphs: [
          "A good risk view treats cash as a cushion and margin as an amplifier: cash lowers your effective volatility, a loan raises it. Seeing both in one Health Score keeps the leverage honest.",
        ],
      },
    ],
    faqs: [
      {
        q: "How much margin is 'safe'?",
        a: "There's no universal safe level — it depends on the volatility of what you hold and your cushion to the maintenance line. The same leverage on a low-vol bond book and a high-beta growth book are very different risks.",
      },
      {
        q: "What triggers a margin call?",
        a: "Your account equity falling below the broker's maintenance margin requirement, usually because the positions you bought on margin dropped in value. The more volatile and concentrated the book, the easier it is to breach.",
      },
    ],
    related: ["portfolio-risk-management", "stress-testing", "options-risk"],
  },
  {
    slug: "options-risk",
    title: "Options risk: delta, gamma, theta, and assignment",
    metaTitle: "Options Risk Explained — Greeks, Short Gamma & Assignment",
    description:
      "Options aren't just another line item. The Greeks (delta, gamma, theta, vega) and short-option risks like assignment and unlimited loss change your whole book.",
    eyebrow: "Derivatives",
    intro:
      "An option position can carry the directional punch of far more stock than its dollar value suggests — and a sold option can lose far more than the premium collected. The Greeks make that exposure measurable.",
    sections: [
      {
        heading: "Delta: your real directional exposure",
        paragraphs: [
          "Delta is how much an option moves per $1 in the underlying. A single call with 0.6 delta on a $300 stock behaves like ~60 shares — about $18,000 of directional exposure from one contract.",
          "Summed across a book, net delta tells you how stock-like your options really are. Two 'small' option positions can add up to a large hidden bet.",
        ],
      },
      {
        heading: "Gamma and theta: speed and bleed",
        paragraphs: [
          "Gamma is how fast delta changes as the stock moves. Long options are long gamma (losses decelerate, gains accelerate); short options are short gamma — losses accelerate on a gap move, which is how option sellers blow up.",
          "Theta is time decay: long options bleed value each day, short options collect it. A book that's net short premium earns theta but is implicitly short volatility.",
        ],
        example: {
          label: "Example",
          body: "A naked short call has limited gain (the premium) and unbounded loss if the stock rips. A short put's worst case is the stock going to zero — strike × 100 per contract. Sizing matters more than the premium.",
        },
      },
      {
        heading: "Assignment and collateral",
        paragraphs: [
          "Short options that finish in-the-money can be assigned — you're forced to buy or deliver shares. A short put needs cash to secure it; a short call should usually be covered by stock you hold.",
          "Folding options into the portfolio view (net delta, short gamma, theta/day, assignment risk near expiry) keeps these positions from hiding in the cracks.",
        ],
      },
    ],
    faqs: [
      {
        q: "Is selling options safer than buying?",
        a: "Not inherently. Selling collects premium and earns theta, but a sold option can lose far more than the premium — a naked short call is theoretically unlimited. The risk is in the tail, not the typical day.",
      },
      {
        q: "What does 'short gamma' mean for my portfolio?",
        a: "It means your losses speed up as the underlying moves against you — small moves are fine, big gap moves hurt disproportionately. Net short gamma is a sign the book is implicitly short volatility.",
      },
    ],
    related: ["margin-risk", "stress-testing", "portfolio-risk-management"],
  },
  {
    slug: "stock-research",
    title: "How to research a stock: a risk-first checklist",
    metaTitle: "How to Research a Stock — A Risk-First, Source-Backed Checklist",
    description:
      "A practical framework for researching a stock: valuation vs peers, growth and profitability quality, the analyst view, and the data gaps that should lower your confidence.",
    eyebrow: "Equity research",
    intro:
      "Good research isn't a single verdict — it's a structured read of valuation, quality, growth, and the Street's view, with honest flags for where the data is thin. The goal is to know what would change your mind, not to be told 'buy'.",
    sections: [
      {
        heading: "Valuation only means something relative to peers and history",
        paragraphs: [
          "A 30× P/E is cheap for some businesses and expensive for others. Compare the multiple to close peers and to the company's own history before calling it rich or cheap.",
          "Pair the multiple with growth: a high P/E backed by 25% revenue CAGR is a different story than the same multiple on a no-growth name.",
        ],
        example: {
          label: "Example",
          body: "If a stock trades at 28× earnings while its peer median is 20×, it's priced at a ~40% premium — justified only if its growth or margins are meaningfully better. The band (cheap / in-line / rich) falls out of that comparison.",
        },
      },
      {
        heading: "Quality and growth: is the business actually good?",
        paragraphs: [
          "Margins (gross, operating, net), returns on capital (ROE/ROIC), and balance-sheet health (debt/equity, interest coverage) describe quality. High returns on capital with low leverage is the durable combination.",
          "Growth needs to be both real and profitable: revenue CAGR and EPS CAGR together, not revenue growth funded by dilution or debt.",
        ],
      },
      {
        heading: "Treat data gaps as part of the answer",
        paragraphs: [
          "When fundamentals, peers, or analyst data are missing or stale, your confidence should fall — not be papered over. A research view is only as good as the data behind it, so every figure should carry its source and freshness.",
          "The most useful output isn't a rating; it's a clear bull case, bear case, and a short list of what would change the view.",
        ],
      },
    ],
    faqs: [
      {
        q: "Should stock research tell me whether to buy?",
        a: "A risk-first approach avoids buy/sell calls. It lays out the favorable and unfavorable evidence, the key risks, and what would change the thesis — leaving the decision, and its fit with your portfolio, to you.",
      },
      {
        q: "Why does data source and freshness matter so much?",
        a: "A valuation built on a stale or missing number can be badly wrong. Knowing which provider supplied each figure and when lets you weight a confident, well-sourced read differently from a thin one.",
      },
    ],
    related: ["portfolio-risk-management", "factor-exposure", "var-cvar-explained"],
  },
];

export const LEARN_BY_SLUG: Record<string, LearnTopic> = Object.fromEntries(
  LEARN_TOPICS.map((t) => [t.slug, t]),
);

export const LEARN_SLUGS = LEARN_TOPICS.map((t) => t.slug);
