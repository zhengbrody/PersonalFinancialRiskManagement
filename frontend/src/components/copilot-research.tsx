"use client";

import type { CopilotResearch, ResearchHypothesis } from "@/lib/copilot-research";
import { Button } from "@/components/ui/button";

const labels: Record<string, string> = {
  "valuation.pe": "P/E", "quality.net_margin": "Net margin",
  "quality.debt_to_equity": "Debt / equity", "growth.revenue_cagr": "Revenue CAGR",
};
const statusText: Record<ResearchHypothesis["status"], string> = {
  unverified: "Unverified", supported_by_evidence: "Threshold met by latest provider value",
  contradicted: "Contradicted by latest provider value", stale: "Stale data — not decided",
};
const missingText: Record<string, string> = {
  no_authorized_source: "No authorized document source is connected",
  reporting_period_unavailable: "Financial reporting period unknown",
  observation_missing: "Value missing", observation_stale: "Value stale",
  observation_undated: "Value undated", no_testable_predicate: "No measurable metric and threshold stated",
  cited_source_not_retrieved: "Cited source not retrieved or verified",
};
const cmp = { gt: ">", ge: "≥", lt: "<", le: "≤" } as const;

function metricOf(context: CopilotResearch, id: string) {
  return labels[id.slice(context.ticker.length + 1)] ?? id;
}

function HypothesisCard({ context, h, onTest }: {
  context: CopilotResearch; h: ResearchHypothesis; onTest?: (h: ResearchHypothesis) => void;
}) {
  const evidence = context.observations.filter(o => h.evidence_observation_ids.includes(o.id));
  return <article aria-label={`Hypothesis ${h.id}`} className="min-w-0 space-y-2 border-t border-border pt-2">
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <span className="rounded-full border border-border px-2 py-0.5">{h.claim_basis === "user_assumption" ? "Your assumption" : "MindMarket inference"}</span>
      <span className="rounded-full border border-border px-2 py-0.5">{statusText[h.status]}</span>
    </div>
    <p className="break-words font-medium">{h.claim}</p>
    {h.test && <p className="text-xs">Test: {metricOf(context, h.test.observation_id)} {cmp[h.test.comparator]} {h.test.unit === "fraction" ? `${+(h.test.threshold * 100).toFixed(4)}%` : `${h.test.threshold}×`} (your threshold)</p>}
    <div className="text-xs">
      <p className="font-medium">Research evidence</p>
      {evidence.length ? <ul className="list-disc pl-4">{evidence.map(o => <li key={o.id} className="break-words">
        {metricOf(context, o.id)}: {o.value == null ? "missing" : o.unit === "fraction" ? `${(o.value * 100).toFixed(1)}%` : `${o.value.toFixed(2)}×`} · {o.status} · {o.source} · provider time {o.source_as_of ?? "unknown"}
      </li>)}</ul> : <p className="text-muted-foreground">None linked.</p>}
    </div>
    {h.inference.length > 0 && <div className="text-xs"><p className="font-medium">Model inference (not evidence)</p>
      <ul className="list-disc pl-4 text-muted-foreground">{h.inference.map(t => <li key={t}>{t}</li>)}</ul></div>}
    <div className="text-xs"><p className="font-medium">Sources</p>
      <ul className="list-disc pl-4 text-muted-foreground">{h.sources.map(src => <li key={src.id} className="break-words">
        {src.source_type === "user_statement" ? "Your message" : src.url
          ? <a href={src.url} target="_blank" rel="noopener noreferrer" className="text-primary underline">{src.author ?? src.publisher ?? src.id}</a>
          : (src.publisher ?? src.id)}
        {" · "}{src.paraphrase ? "paraphrase" : `quote · ${src.quote_locator}`}
        {" · "}{src.source_type === "method_card" ? "reviewed" : "retrieved"} {src.retrieved_at ?? "unknown"}
        {" · published "}{src.published_at ?? "unknown"}{" · "}{src.verification.replace(/_/g, " ")}
      </li>)}</ul></div>
    <div className="text-xs"><p className="font-medium">Counterpoints</p>
      <ul className="list-disc pl-4">{h.counter_arguments.map(t => <li key={t}>{t}</li>)}</ul></div>
    <div className="text-xs"><p className="font-medium">What would refute it</p>
      <ul className="list-disc pl-4">{h.invalidation_conditions.map(c => <li key={c.description}>{c.description}</li>)}</ul></div>
    {h.missing.length > 0 && <p className="text-xs text-muted-foreground">Missing: {h.missing.map(m => missingText[m.reason] ?? m.reason).filter((v, i, a) => a.indexOf(v) === i).join(" · ")}</p>}
    {onTest && <Button type="button" size="sm" variant="outline" onClick={() => onTest(h)}>Test in account comparison</Button>}
  </article>;
}

export function CopilotResearchPanel({ research, onTestHypothesis }: {
  research: CopilotResearch[]; onTestHypothesis?: (h: ResearchHypothesis) => void;
}) {
  if (!research.length) return null;
  return <section aria-label="Research context" className="space-y-3">
    <h4 className="text-sm font-semibold">Research context & hypotheses to test</h4>
    <p className="text-xs text-muted-foreground">Company research does not establish account suitability. Status compares one provider value with a stated threshold; it does not prove a thesis.</p>
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
        {context.hypotheses.length > 0
          ? context.hypotheses.map(h => <HypothesisCard key={h.id} context={context} h={h} onTest={onTestHypothesis} />)
          : context.questions.map(question => <article key={question.method_id} className="space-y-1 border-t border-border pt-2">
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
