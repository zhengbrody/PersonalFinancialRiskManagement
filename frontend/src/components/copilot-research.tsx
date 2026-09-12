"use client";

import type { CopilotResearch } from "@/lib/copilot-research";

const labels: Record<string, string> = {
  "valuation.pe": "P/E", "quality.net_margin": "Net margin",
  "quality.debt_to_equity": "Debt / equity", "growth.revenue_cagr": "Revenue CAGR",
};

export function CopilotResearchPanel({ research }: { research: CopilotResearch[] }) {
  if (!research.length) return null;
  return <section aria-label="Research context" className="space-y-3">
    <h4 className="text-sm font-semibold">Research context & questions to test</h4>
    <p className="text-xs text-muted-foreground">Company research does not establish account suitability. Hypotheses remain untested.</p>
    {research.map(context => <details key={context.ticker} className="rounded-lg border border-border p-3">
      <summary className="cursor-pointer text-sm font-medium">{context.ticker} · {context.status}</summary>
      <div className="mt-3 space-y-3 text-sm">
        <p className="text-xs text-muted-foreground">Prepared {context.captured_at}</p>
        <dl className="grid gap-2 sm:grid-cols-2">
          {context.observations.map(row => <div key={row.id} className="min-w-0 rounded border border-border p-2">
            <dt className="font-medium">{labels[row.metric] ?? row.metric}</dt>
            <dd>{row.value == null ? "Missing" : row.unit === "fraction" ? `${(row.value * 100).toFixed(1)}%` : `${row.value.toFixed(2)}×`} · {row.status}</dd>
            <dd className="break-words text-xs text-muted-foreground">{row.basis === "computed_from_series" ? "Calculated using " : ""}{row.source} · block-level attribution<br />Provider timestamp: {row.source_as_of ?? "unknown"}<br />Reporting period: unknown</dd>
          </div>)}
        </dl>
        {context.questions.map(question => <article key={question.method_id} className="space-y-1 border-t border-border pt-2">
          <p className="font-medium">{question.hypothesis}</p>
          <p className="text-xs text-muted-foreground">Check against: {question.observation_ids.map(id => labels[id.slice(context.ticker.length + 1)]).join(", ")} · not tested</p>
          <p>Counterpoint: {question.counterpoint}</p>
          <p>What would challenge it: {question.invalidation_check}</p>
          {context.methods.filter(method => method.id === question.method_id).map(method =>
            <a key={method.id} href={method.url} target="_blank" rel="noopener noreferrer" className="text-xs text-primary underline">
              Method: {method.author} · reviewed {method.reviewed_at}
            </a>)}
        </article>)}
        {context.leads.length > 0 && <div className="space-y-2 border-t border-border pt-2">
          <p className="font-medium">External research leads · article content not verified</p>
          {context.leads.map(lead => <div key={lead.url}>
            <a href={lead.url} target="_blank" rel="noopener noreferrer" className="break-words text-primary underline">{lead.title}</a>
            <p className="text-xs text-muted-foreground">{lead.publisher ?? "Publisher unknown"} · {lead.published_at ?? "Date unknown"} · Author unknown · Conflicts not disclosed in feed</p>
          </div>)}
        </div>}
        <details><summary className="cursor-pointer text-xs">Coverage & limitations</summary>
          <ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-muted-foreground">{context.limitations.map(item => <li key={item}>{item}</li>)}</ul>
        </details>
      </div>
    </details>)}
  </section>;
}
