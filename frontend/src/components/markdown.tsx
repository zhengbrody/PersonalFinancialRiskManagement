"use client";

/**
 * Theme-safe GitHub-Flavored Markdown renderer for AI Copilot answers.
 *
 * The assistant emits Markdown (bold headers, bullet lists, and TABLES for
 * metric/holding comparisons). react-markdown does NOT render raw HTML by
 * default, so model output stays XSS-safe (we intentionally omit rehype-raw).
 *
 * Every element is styled with semantic Tailwind theme tokens ONLY — never
 * hardcoded colors — so it reads correctly in the market-synced light/dark
 * theme. Spacing is compact: this renders inside a chat bubble that also
 * lives in a narrow floating panel.
 */

import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

const components: Components = {
  h1: ({ children }) => (
    <h3 className="mt-3 mb-1 text-sm font-semibold text-foreground first:mt-0">{children}</h3>
  ),
  h2: ({ children }) => (
    <h3 className="mt-3 mb-1 text-sm font-semibold text-foreground first:mt-0">{children}</h3>
  ),
  h3: ({ children }) => (
    <h4 className="mt-2 mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground first:mt-0">
      {children}
    </h4>
  ),
  p: ({ children }) => <p className="my-1.5 leading-relaxed text-foreground">{children}</p>,
  ul: ({ children }) => <ul className="my-1.5 list-disc space-y-0.5 pl-5">{children}</ul>,
  ol: ({ children }) => <ol className="my-1.5 list-decimal space-y-0.5 pl-5">{children}</ol>,
  li: ({ children }) => <li className="leading-relaxed">{children}</li>,
  strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="text-primary underline underline-offset-2 hover:opacity-80"
    >
      {children}
    </a>
  ),
  hr: () => <hr className="my-2 border-border" />,
  blockquote: ({ children }) => (
    <blockquote className="my-1.5 border-l-2 border-border pl-3 text-muted-foreground">
      {children}
    </blockquote>
  ),
  code: ({ children }) => (
    <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs text-foreground">
      {children}
    </code>
  ),
  pre: ({ children }) => (
    <pre className="my-2 overflow-x-auto rounded bg-muted p-2 font-mono text-xs text-foreground">
      {children}
    </pre>
  ),
  // Tables: horizontally scrollable so wide metric tables don't overflow the
  // narrow floating panel.
  table: ({ children }) => (
    <div className="my-2 overflow-x-auto">
      <table className="w-full border-collapse text-xs">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead>{children}</thead>,
  th: ({ children }) => (
    <th className="border border-border bg-muted/50 px-2 py-1 text-left font-medium text-foreground">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="border border-border px-2 py-1 text-foreground">{children}</td>
  ),
};

export function Markdown({ children }: { children: string }) {
  return (
    <div className="text-sm">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {children}
      </ReactMarkdown>
    </div>
  );
}
