import Link from "next/link";
import { isBillingEnabled } from "@/lib/billing-flag";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { MacroSnapshot } from "@/components/macro-snapshot";
import { SampleCockpit } from "@/components/sample-cockpit";

const PRODUCT_JSON_LD = {
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  name: "MindMarket",
  applicationCategory: "FinanceApplication",
  operatingSystem: "Web",
  url: "https://mindmarket.app/",
  description:
    "AI portfolio risk analytics for individual investors, including portfolio health score, VaR, CVaR, stress tests, factor exposure, and live US rates data.",
  offers: [
    {
      "@type": "Offer",
      name: "Free",
      price: "0",
      priceCurrency: "USD",
    },
    {
      "@type": "Offer",
      name: "Basic",
      price: "10",
      priceCurrency: "USD",
      priceSpecification: {
        "@type": "UnitPriceSpecification",
        price: "10",
        priceCurrency: "USD",
        billingDuration: "P1M",
      },
    },
  ],
};

const FAQ_JSON_LD = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: [
    {
      "@type": "Question",
      name: "What does MindMarket measure?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "MindMarket measures portfolio health, volatility, Sharpe ratio, max drawdown, VaR, CVaR, factor exposure, stress-test losses, and live macro context.",
      },
    },
    {
      "@type": "Question",
      name: "Does the AI invent portfolio risk numbers?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "No. Risk numbers are calculated by deterministic Python services. AI explanations only summarize already-computed metrics.",
      },
    },
  ],
};

/**
 * Anonymous landing page (the marketing/story view). Signed-in users get the
 * personalized <Dashboard/> instead — see app/page.tsx.
 */
export function MarketingLanding() {
  return (
    <div className="space-y-16">
      <script
        type="application/ld+json"
        suppressHydrationWarning
        dangerouslySetInnerHTML={{ __html: JSON.stringify(PRODUCT_JSON_LD) }}
      />
      <script
        type="application/ld+json"
        suppressHydrationWarning
        dangerouslySetInnerHTML={{ __html: JSON.stringify(FAQ_JSON_LD) }}
      />

      {/* ── hero ─────────────────────────────────────────────── */}
      <section className="space-y-6 text-center md:text-left">
        <p className="text-xs font-medium uppercase tracking-widest text-primary">
          MindMarket AI
        </p>
        <h1 className="text-4xl font-semibold leading-tight tracking-tight md:text-6xl">
          Institutional risk analytics
          <br />
          for your own portfolio.
        </h1>
        <p className="max-w-2xl text-lg text-muted-foreground md:text-xl">
          Connect your holdings, get a 0–1000 Health Score in seconds, and see
          the same VaR, factor exposures, and stress tests hedge funds use —
          without paying $40k for a Bloomberg Terminal.
        </p>
        <div className="flex flex-col gap-3 pt-2 sm:flex-row sm:justify-center md:justify-start">
          <Link href="/demo">
            <Button size="lg" className="w-full sm:w-auto">
              Try a Demo Risk Check
            </Button>
          </Link>
          <Link href="/signup">
            <Button size="lg" variant="outline" className="w-full sm:w-auto">
              Analyze my portfolio
            </Button>
          </Link>
          <Link href="/research">
            <Button size="lg" variant="ghost" className="w-full sm:w-auto">
              Research a stock
            </Button>
          </Link>
        </div>
        <p className="text-xs text-muted-foreground">
          {isBillingEnabled()
            ? "No credit card to start. Free monthly AI credits included."
            : "Free during beta — no credit card, all core features open."}
        </p>
      </section>

      {/* ── live macro panel ─────────────────────────────────── */}
      <MacroSnapshot />

      {/* ── interactive sample cockpit (pre-login, deterministic) ── */}
      <SampleCockpit />

      {/* ── SEO-readable product category ────────────────────── */}
      <section className="grid gap-6 md:grid-cols-[1.2fr_0.8fr]">
        <div className="space-y-3">
          <p className="text-xs font-medium uppercase tracking-widest text-primary">
            Portfolio risk management software
          </p>
          <h2 className="text-3xl font-semibold tracking-tight">
            See what can hurt your portfolio before the market does.
          </h2>
          <p className="text-sm leading-6 text-muted-foreground">
            MindMarket is an AI portfolio risk analytics platform for
            individual investors who want more than a broker balance. It turns
            holdings into a Portfolio Health Score, VaR and CVaR estimates,
            factor exposure, stress-test losses, liquidity checks, and
            plain-English explanations grounded in computed data.
          </p>
        </div>
        <Card>
          <CardHeader>
            <CardTitle>Built for risk questions</CardTitle>
            <CardDescription>
              Search-ready workflows users actually ask for.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2 text-sm text-muted-foreground">
            <p>How risky is my portfolio?</p>
            <p>What is my worst-case drawdown?</p>
            <p>Which holding drives the most VaR?</p>
            <p>How do rates, inflation, and the yield curve affect me?</p>
          </CardContent>
        </Card>
      </section>

      {/* ── feature pillars ──────────────────────────────────── */}
      <section className="space-y-6">
        <div className="space-y-2">
          <p className="text-xs font-medium uppercase tracking-widest text-primary">
            Why MindMarket
          </p>
          <h2 className="text-3xl font-semibold tracking-tight">
            Real risk math, not LLM guesswork.
          </h2>
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          <Card>
            <CardHeader>
              <CardTitle>Portfolio Health Score</CardTitle>
              <CardDescription>
                A single 0–1000 number that says how risk-appropriate your
                portfolio is — broken down into three institutional-grade
                dimensions you can act on.
              </CardDescription>
            </CardHeader>
            <CardContent className="text-sm text-muted-foreground">
              Risk Match · Risk-Adjusted Return · Downside Protection
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Real risk metrics</CardTitle>
              <CardDescription>
                Monte Carlo VaR, CVaR, six-factor regression, stress tests,
                drawdown analysis. The math the pros use, on your account.
              </CardDescription>
            </CardHeader>
            <CardContent className="text-sm text-muted-foreground">
              VaR 95 / 99 · factor betas · component VaR · liquidity
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Live market context</CardTitle>
              <CardDescription>
                Real Fed Funds rate, CPI, unemployment, US Treasury curve
                streamed live so you score your portfolio against the macro
                regime that actually exists today.
              </CardDescription>
            </CardHeader>
            <CardContent className="text-sm text-muted-foreground">
              FRED · US Treasury · refreshed hourly
            </CardContent>
          </Card>
        </div>
      </section>

      {/* ── how it works ─────────────────────────────────────── */}
      <section className="space-y-6">
        <div className="space-y-2">
          <p className="text-xs font-medium uppercase tracking-widest text-primary">
            How it works
          </p>
          <h2 className="text-3xl font-semibold tracking-tight">
            Three minutes to your first score.
          </h2>
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          <Step
            n="1"
            title="Sign up"
            body="Email + password. Free forever, with monthly AI credits to try everything."
          />
          <Step
            n="2"
            title="Add your holdings"
            body="Tickers + shares. Optionally avg-cost for P&L tracking. Edit any time."
          />
          <Step
            n="3"
            title="Score & analyze"
            body="One click → 0–1000 score, dimension breakdown, and the full risk report."
          />
        </div>
      </section>

      {/* ── pricing teaser (hidden during the free beta) ─────────── */}
      {isBillingEnabled() && (
        <section className="space-y-4">
          <div className="space-y-2">
            <p className="text-xs font-medium uppercase tracking-widest text-primary">
              Pricing
            </p>
            <h2 className="text-3xl font-semibold tracking-tight">
              Free to try. $10/mo to scale.
            </h2>
          </div>
          <Card className="border-primary/30">
            <CardContent className="grid gap-4 p-6 md:grid-cols-3">
              <PriceMini label="Free" price="$0" detail="25 AI credits / mo" />
              <PriceMini label="Basic" price="$10" detail="300 AI credits / mo" highlight />
              <PriceMini label="Pro" price="$25" detail="800 AI credits / mo" />
            </CardContent>
          </Card>
          <p className="text-sm">
            <Link href="/pricing" className="text-primary hover:underline">
              Compare full plans →
            </Link>
          </p>
        </section>
      )}

      {/* ── advanced workbench ───────────────────────────────── */}
      <section className="space-y-3 rounded-xl border border-border bg-card p-6">
        <h2 className="text-lg font-semibold">Need more depth?</h2>
        <p className="text-sm text-muted-foreground">
          The full institutional workbench — SEC 13F smart-money flows, the
          options scanner, factor attribution, and a Bloomberg-style trading
          floor — is available on the advanced dashboard.
        </p>
        <div className="flex flex-wrap gap-3 pt-2">
          <a href="/legacy/1_Overview">
            <Button variant="outline" size="sm">
              Open advanced dashboard
            </Button>
          </a>
        </div>
      </section>

      {/* ── learn (SEO hub) ──────────────────────────────────────
          Plain <a> links: these are static HTML pages served by Caddy from
          assets/seo/, not Next routes — next/link prefetch would 404 in dev
          and adds nothing for full-page navigations. They give crawlers an
          in-content path to the topic pages (previously sitemap-only). */}
      <section className="space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-lg font-semibold">Learn portfolio risk</h2>
          <div className="flex gap-3 text-sm">
            <Link href="/product" className="text-primary hover:underline">
              How it works →
            </Link>
            <Link href="/learn" className="text-primary hover:underline">
              All guides →
            </Link>
          </div>
        </div>
        <ul className="grid gap-x-6 gap-y-1.5 text-sm sm:grid-cols-2 lg:grid-cols-3">
          {LEARN_LINKS.map((l) => (
            <li key={l.href}>
              <a href={l.href} className="text-muted-foreground hover:text-primary hover:underline">
                {l.label}
              </a>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

const LEARN_LINKS = [
  { href: "/portfolio-risk-management", label: "Personal portfolio risk management" },
  { href: "/ai-portfolio-analysis", label: "AI portfolio analysis" },
  { href: "/portfolio-var-stress-testing", label: "VaR & stress testing explained" },
  { href: "/portfolio-stress-test", label: "Stress-test your portfolio" },
  { href: "/stock-portfolio-concentration-risk", label: "Concentration risk in stock portfolios" },
  { href: "/margin-risk-calculator", label: "Margin risk calculator" },
  { href: "/robinhood-margin-risk", label: "Margin risk on Robinhood" },
  { href: "/sample-risk-report", label: "Sample risk report" },
  { href: "/about", label: "About MindMarket" },
];

function Step({ n, title, body }: { n: string; title: string; body: string }) {
  return (
    <div className="space-y-2 rounded-lg border border-border bg-card p-5">
      <div className="flex h-8 w-8 items-center justify-center rounded-full border border-primary/40 bg-primary/10 font-mono text-sm font-semibold text-primary">
        {n}
      </div>
      <h3 className="text-base font-semibold">{title}</h3>
      <p className="text-sm text-muted-foreground">{body}</p>
    </div>
  );
}

function PriceMini({
  label,
  price,
  detail,
  highlight,
}: {
  label: string;
  price: string;
  detail: string;
  highlight?: boolean;
}) {
  return (
    <div
      className={
        "space-y-1 rounded-md border p-4 " +
        (highlight ? "border-primary/40 bg-primary/5" : "border-border bg-background")
      }
    >
      <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="font-mono text-2xl">
        {price}
        <span className="ml-1 text-xs text-muted-foreground">/mo</span>
      </p>
      <p className="text-xs text-muted-foreground">{detail}</p>
    </div>
  );
}
