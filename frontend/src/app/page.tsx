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
          MindMarket — Next.js shell · Phase 2
        </p>
        <h1 className="text-4xl font-semibold tracking-tight md:text-5xl">
          Portfolio risk, scored in under a second.
        </h1>
        <p className="max-w-2xl text-muted-foreground">
          Phase-2 frontend skeleton. The score page below calls the
          FastAPI backend at <code className="font-mono">/api/v1/risk/score</code>{" "}
          using the typed envelope wrapper. No production deploy yet.
        </p>
        <div className="flex gap-3 pt-2">
          <Link href="/score">
            <Button size="lg">Try the score endpoint →</Button>
          </Link>
          <a
            href="http://localhost:8000/docs"
            target="_blank"
            rel="noreferrer"
          >
            <Button size="lg" variant="outline">
              FastAPI docs
            </Button>
          </a>
        </div>
      </section>

      <MacroSnapshot />

      <section className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Envelope contract</CardTitle>
            <CardDescription>
              Every backend call returns{" "}
              <code className="font-mono">{"{data, error, meta}"}</code>. The
              client wrapper unwraps it once.
            </CardDescription>
          </CardHeader>
          <CardContent className="font-mono text-xs text-muted-foreground">
            apiFetch&lt;ScoreResponse&gt;(&quot;/api/v1/risk/score&quot;, {"{ ... }"})
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Stateless quant API</CardTitle>
            <CardDescription>
              No Supabase round-trip on /risk/score. Same Pydantic input
              boundary as the Streamlit Copilot page.
            </CardDescription>
          </CardHeader>
          <CardContent className="text-xs text-muted-foreground">
            Public endpoint by design — testable offline.
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Streamlit untouched</CardTitle>
            <CardDescription>
              The legacy app keeps running on{" "}
              <span className="font-mono">mindmarket.app</span> while the new
              shell lives only on localhost.
            </CardDescription>
          </CardHeader>
          <CardContent className="text-xs text-muted-foreground">
            Phase 5 will route /api/v1 to FastAPI via Caddy.
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
