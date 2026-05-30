import Link from "next/link";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { MacroSnapshot } from "@/components/macro-snapshot";

export default function Home() {
  return (
    <div className="space-y-16">
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
          <Link href="/signup">
            <Button size="lg" className="w-full sm:w-auto">
              Get started — free
            </Button>
          </Link>
          <Link href="/pricing">
            <Button size="lg" variant="outline" className="w-full sm:w-auto">
              See plans
            </Button>
          </Link>
        </div>
        <p className="text-xs text-muted-foreground">
          No credit card to start. 2 free portfolio analyses per month.
        </p>
      </section>

      {/* ── live macro panel ─────────────────────────────────── */}
      <MacroSnapshot />

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
            body="Email + password. Free forever for the first two analyses each month."
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

      {/* ── pricing teaser ───────────────────────────────────── */}
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
            <PriceMini label="Free" price="$0" detail="2 analyses + 2 chats / mo" />
            <PriceMini label="Basic" price="$10" detail="30 analyses + 100 chats / mo" highlight />
            <PriceMini label="Pro" price="$25" detail="100 analyses + 300 chats / mo" />
          </CardContent>
        </Card>
        <p className="text-sm">
          <Link href="/pricing" className="text-primary hover:underline">
            Compare full plans →
          </Link>
        </p>
      </section>

      {/* ── advanced workbench ───────────────────────────────── */}
      <section className="space-y-3 rounded-xl border border-border bg-card p-6">
        <h2 className="text-lg font-semibold">Need more depth?</h2>
        <p className="text-sm text-muted-foreground">
          The full institutional workbench — VIX & yield-curve regime, SEC 13F
          smart-money flows, options scanner, backtesting, factor attribution,
          and the AI Portfolio Copilot — is available on the legacy dashboard.
        </p>
        <div className="flex flex-wrap gap-3 pt-2">
          <a href="/legacy/1_Overview">
            <Button variant="outline" size="sm">
              Open advanced dashboard
            </Button>
          </a>
          <a href="/legacy/11_Portfolio_Copilot_Beta">
            <Button variant="ghost" size="sm">
              AI Copilot →
            </Button>
          </a>
        </div>
      </section>
    </div>
  );
}

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
        (highlight
          ? "border-primary/40 bg-primary/5"
          : "border-border bg-background")
      }
    >
      <p className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className="font-mono text-2xl">
        {price}
        <span className="ml-1 text-xs text-muted-foreground">/mo</span>
      </p>
      <p className="text-xs text-muted-foreground">{detail}</p>
    </div>
  );
}
