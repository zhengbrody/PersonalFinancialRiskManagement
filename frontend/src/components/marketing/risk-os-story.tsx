/** Shared, crawlable Portfolio Risk OS story used across public pages. */

import Link from "next/link";
import { COMPARISON_CAPABILITIES, PRODUCT_SURFACES, RISK_WORKFLOW } from "@/lib/product-story";
import { C, mono } from "./theme";

/** Visible limitations accompany each capability, including in server HTML. */
export function ComparisonCapabilities() {
  return (
    <div style={{ display: "grid", gap: 16 }}>
      {COMPARISON_CAPABILITIES.map((capability) => (
        <article key={capability.key} style={{ border: `1px solid ${C.hair}`, borderRadius: 16, padding: 22 }}>
          <h3 style={{ color: C.paper, fontSize: 18, margin: "0 0 10px" }}>{capability.title}</h3>
          <p style={{ color: C.slate, lineHeight: 1.6, margin: "0 0 10px" }}>{capability.body}</p>
          <p style={{ color: C.slate, fontSize: 14, lineHeight: 1.6, margin: 0 }}><strong>Scope: </strong>{capability.limitation}</p>
        </article>
      ))}
    </div>
  );
}

export function RiskWorkflow({ compact = false }: { compact?: boolean }) {
  return (
    <ol
      className="mm-workflow-grid"
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(5,minmax(0,1fr))",
        gap: compact ? 10 : 14,
        listStyle: "none",
        margin: 0,
        padding: 0,
      }}
    >
      {RISK_WORKFLOW.map((stage, index) => (
        <li
          key={stage.key}
          style={{
            position: "relative",
            borderRadius: compact ? 12 : 16,
            border: `1px solid ${C.hair}`,
            background: C.surfaceFaint,
            padding: compact ? "14px" : "20px",
            minHeight: compact ? 150 : 190,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span
              aria-hidden="true"
              style={{
                ...mono,
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                width: 24,
                height: 24,
                borderRadius: 999,
                color: C.ctaFg,
                background: C.ctaBg,
                fontSize: 11,
                fontWeight: 700,
              }}
            >
              {index + 1}
            </span>
            <span
              style={{
                fontSize: 11,
                fontWeight: 700,
                textTransform: "uppercase",
                letterSpacing: ".1em",
                color: C.teal,
              }}
            >
              {stage.label}
            </span>
          </div>
          <h3 style={{ color: C.paper, fontSize: compact ? 15 : 17, margin: "14px 0 7px" }}>
            {stage.title}
          </h3>
          <p style={{ color: C.slate, fontSize: compact ? 13 : 14, lineHeight: 1.55, margin: 0 }}>
            {stage.body}
          </p>
          {index < RISK_WORKFLOW.length - 1 && (
            <span className="mm-workflow-arrow" aria-hidden="true">
              →
            </span>
          )}
        </li>
      ))}
    </ol>
  );
}

export function ProductSurfaceGrid() {
  return (
    <div
      className="mm-surface-grid"
      style={{ display: "grid", gridTemplateColumns: "repeat(6,minmax(0,1fr))", gap: 16 }}
    >
      {PRODUCT_SURFACES.map((surface, index) => (
        <Link
          key={surface.key}
          id={surface.key === "research" ? "research-to-test" : surface.key}
          href={surface.href}
          className="mm-card"
          style={{
            gridColumn: index < 3 ? "span 2" : "span 3",
            borderRadius: 16,
            border: `1px solid ${C.hair}`,
            background: C.cardGrad,
            padding: 22,
            textDecoration: "none",
            color: "inherit",
          }}
        >
          <p
            style={{
              color: C.teal,
              fontSize: 11,
              fontWeight: 700,
              letterSpacing: ".1em",
              textTransform: "uppercase",
              margin: 0,
            }}
          >
            {surface.tag}
          </p>
          <h3 style={{ color: C.paper, fontSize: 18, margin: "10px 0 7px" }}>{surface.title}</h3>
          <p style={{ color: C.slate, fontSize: 14, lineHeight: 1.6, margin: 0 }}>{surface.body}</p>
        </Link>
      ))}
    </div>
  );
}
