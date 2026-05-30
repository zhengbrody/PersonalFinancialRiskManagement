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
    <div className="space-y-12">
      <section className="space-y-4">
        <p className="text-xs font-medium uppercase tracking-widest text-primary">
          MindMarket AI · Portfolio Risk Platform
        </p>
        <h1 className="text-4xl font-semibold tracking-tight md:text-5xl">
          Portfolio risk analytics for individual investors.
        </h1>
        <p className="max-w-2xl text-muted-foreground">
          Connect a portfolio, run deterministic risk scoring, and review
          market-aware diagnostics backed by the FastAPI quant engine. The
          legacy Streamlit workbench remains available during the migration.
        </p>
        <div className="flex gap-3 pt-2">
          <Link href="/signup">
            <Button size="lg">Create account</Button>
          </Link>
          <Link href="/portfolios">
            <Button size="lg" variant="outline">
              Open portfolios
            </Button>
          </Link>
        </div>
      </section>

      <MacroSnapshot />

      <section className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Typed API contract</CardTitle>
            <CardDescription>
              Every backend call returns{" "}
              <code className="font-mono">{"{data, error, meta}"}</code>. The
              frontend unwraps it once and renders consistent loading and
              error states.
            </CardDescription>
          </CardHeader>
          <CardContent className="font-mono text-xs text-muted-foreground">
            /api/v1/risk/score_from_active
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Deterministic quant engine</CardTitle>
            <CardDescription>
              VaR, CVaR, Sharpe, drawdown, factor exposure, and stress
              metrics are computed by Python services, not guessed by an LLM.
            </CardDescription>
          </CardHeader>
          <CardContent className="text-xs text-muted-foreground">
            Same risk primitives power the app, API, and MCP tools.
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Legacy workbench</CardTitle>
            <CardDescription>
              The original Streamlit dashboard still runs behind{" "}
              <span className="font-mono">/legacy</span> for beta workflows and
              emergency rollback.
            </CardDescription>
          </CardHeader>
          <CardContent className="text-xs text-muted-foreground">
            New users should start with account signup and portfolio creation.
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
