"use client";

/** Shared, input-free renderer for the existing grounded six-section contract. */
import { DataConfidence } from "@/components/data-confidence";
import { Markdown } from "@/components/markdown";
import type {
  CopilotAnswer,
  CopilotEvidence,
  CopilotSection,
} from "@/lib/queries";

const SOURCE_STYLE: Record<string, string> = {
  engine: "border-primary/40 bg-primary/10 text-primary",
  fmp: "border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  yfinance: "border-sky-500/40 bg-sky-500/10 text-sky-600 dark:text-sky-400",
  macro:
    "border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400",
  derived:
    "border-violet-500/40 bg-violet-500/10 text-violet-600 dark:text-violet-400",
  reference: "border-border bg-muted text-muted-foreground",
  glossary: "border-border bg-muted text-muted-foreground",
};

// Friendly names for the deterministic tools behind evidence rows — user
// language, not API internals.
const TOOL_LABEL: Record<string, string> = {
  portfolio_score: "Portfolio health engine",
  factpack: "Stock fact pack",
  macro_regime: "Market regime feed",
  glossary: "Metric glossary",
  options_exposure: "Options exposure engine",
  risk_reference: "Risk reference bands",
  score_change: "Score-change attribution",
  ticker_exposure: "Your-book exposure",
  optimizer: "Portfolio scans",
  simulation: "What-if simulation",
  user_preferences: "Your confirmed preferences",
};

function sourceClass(source: string): string {
  return SOURCE_STYLE[source] ?? SOURCE_STYLE.glossary;
}

export function CopilotAnswerCard({ answer }: { answer: CopilotAnswer }) {
  const sections = answer.sections ?? [];
  const directionalBlocked =
    answer.data_confidence != null &&
    answer.data_confidence.directional_allowed === false;
  return (
    <div className="space-y-4 rounded-lg border border-border bg-card/50 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full border border-primary/40 bg-primary/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-primary">
          {answer.intent.replace(/_/g, " ")}
        </span>
        {answer.tickers.map((t) => (
          <span
            key={t}
            className="rounded-full border border-border bg-muted px-2 py-0.5 text-[10px] font-medium"
          >
            {t}
          </span>
        ))}
        {answer.data_only && (
          <span className="text-[10px] text-muted-foreground">
            data-driven answer
          </span>
        )}
      </div>

      {directionalBlocked && (
        <div
          role="status"
          className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-muted-foreground"
        >
          Not enough verified data for a directional answer — the sections below
          show what is known and what&apos;s missing.
        </div>
      )}

      {sections.length > 0 ? (
        <div className="space-y-3">
          {sections
            .filter((s) =>
              ["direct_answer", "portfolio_relevance"].includes(s.key),
            )
            .map((s) => (
              <AnswerSection key={s.key} section={s} answer={answer} />
            ))}
          <details className="rounded-lg border border-border p-3">
            <summary className="cursor-pointer text-sm font-medium">
              {answer.language === "zh"
                ? "证据、假设与局限"
                : "Evidence, assumptions & limits"}
            </summary>
            <div className="mt-3 space-y-3">
              {sections
                .filter(
                  (s) =>
                    !["direct_answer", "portfolio_relevance"].includes(s.key),
                )
                .map((s) => (
                  <AnswerSection key={s.key} section={s} answer={answer} />
                ))}
            </div>
          </details>
          {answer.disclaimer && (
            <p className="text-[11px] italic text-muted-foreground">
              {answer.disclaimer}
            </p>
          )}
        </div>
      ) : (
        // Pre-sections (cached/legacy) answers keep the original flat render:
        // markdown + confidence + the evidence strip.
        <div className="space-y-4">
          <div className="text-[15px] leading-relaxed">
            <Markdown>{answer.answer_markdown}</Markdown>
          </div>
          <DataConfidence
            confidence={answer.data_confidence}
            title="Answer confidence"
          />
          {answer.evidence.length > 0 && (
            <div className="border-t border-border pt-3">
              <EvidenceSection
                title="Evidence — every number above is one of these vetted facts"
                evidence={answer.evidence}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function AnswerSection({
  section,
  answer,
}: {
  section: CopilotSection;
  answer: CopilotAnswer;
}) {
  if (section.key === "evidence") {
    return <EvidenceSection title={section.title} evidence={answer.evidence} />;
  }
  if (section.key === "data_confidence") {
    return (
      <section aria-label={section.title} className="space-y-2">
        <SectionTitle title={section.title} />
        <div className="text-sm leading-relaxed text-muted-foreground">
          <Markdown>{section.markdown}</Markdown>
        </div>
        <DataConfidence confidence={answer.data_confidence} title="Details" />
      </section>
    );
  }
  if (section.key === "simulation") {
    return (
      <section
        aria-label={section.title}
        className="space-y-1 rounded-lg border border-dashed border-sky-500/50 bg-sky-500/5 p-3"
      >
        <div className="flex items-center gap-2">
          <SectionTitle title={section.title} />
          <span className="rounded-full border border-sky-500/40 bg-sky-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-sky-600 dark:text-sky-400">
            what-if · not a market fact
          </span>
        </div>
        <div className="text-sm leading-relaxed">
          <Markdown>{section.markdown}</Markdown>
        </div>
      </section>
    );
  }
  return (
    <section aria-label={section.title} className="space-y-1">
      <div className="flex items-center gap-2">
        <SectionTitle title={section.title} />
        {section.ai_generated && (
          <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
            AI-phrased · numbers verified
          </span>
        )}
      </div>
      <div
        className={
          section.key === "direct_answer"
            ? "text-[15px] font-medium leading-relaxed"
            : "text-sm leading-relaxed"
        }
      >
        <Markdown>{section.markdown}</Markdown>
      </div>
    </section>
  );
}

function SectionTitle({ title }: { title: string }) {
  return (
    <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
      {title}
    </h4>
  );
}

function EvidenceSection({
  title,
  evidence,
}: {
  title: string;
  evidence: CopilotEvidence[];
}) {
  if (!evidence.length) {
    return (
      <section aria-label={title} className="space-y-1">
        <SectionTitle title={title} />
        <p className="text-sm text-muted-foreground">
          No verified data was available for this answer.
        </p>
      </section>
    );
  }
  return (
    <section aria-label={title} className="space-y-2">
      <SectionTitle title={title} />
      <p className="text-xs text-muted-foreground">
        Every number above comes from one of these vetted facts — expand any row
        for its source.
      </p>
      <ul className="space-y-1">
        {evidence.map((e, i) => (
          <EvidenceRow key={`${e.id ?? e.label}-${i}`} item={e} />
        ))}
      </ul>
    </section>
  );
}

function EvidenceRow({ item }: { item: CopilotEvidence }) {
  return (
    <li>
      <details className="group rounded-md border border-border bg-background">
        <summary
          className="flex cursor-pointer list-none flex-wrap items-center gap-1.5 px-2 py-1.5 text-xs [&::-webkit-details-marker]:hidden"
          aria-label={`Evidence: ${item.label}`}
        >
          {item.id && (
            <span className="rounded bg-muted px-1 font-mono text-[10px] text-muted-foreground">
              {item.id}
            </span>
          )}
          <span className="text-muted-foreground">{item.label}:</span>
          <span className="font-medium">{item.value}</span>
          <span
            className={`ml-auto rounded px-1 py-0.5 text-[10px] font-semibold uppercase ${sourceClass(item.source)}`}
          >
            {item.source}
          </span>
        </summary>
        <div className="border-t border-border px-2 py-1.5 text-[11px] text-muted-foreground">
          <span className="font-medium">Computed by:</span>{" "}
          {TOOL_LABEL[item.tool ?? ""] ?? item.tool ?? "platform data"}
          {item.source_type ? ` · ${item.source_type} source` : null}
        </div>
      </details>
    </li>
  );
}
