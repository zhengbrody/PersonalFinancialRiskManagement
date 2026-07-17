/** Shared, crawlable Portfolio Risk OS story used across public pages. */

import Link from "next/link";
import { PRODUCT_SURFACES, RISK_WORKFLOW } from "@/lib/product-story";
import { C, mono } from "./theme";

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

export function RiskOsPreview() {
  const priorities = [
    ["Concentration", "NVDA is 22% of sample value", "Test reduction"],
    ["Market context", "Volatility pressure increased", "Open Analyze"],
    ["Plan review", "Two saved decisions need review", "Review plans"],
  ];
  return (
    <div
      aria-label="Illustrative Today action center"
      style={{
        borderRadius: 22,
        border: `1px solid ${C.hair}`,
        background: C.cardGrad,
        boxShadow: "0 40px 90px -40px rgba(0,0,0,.8)",
        padding: 22,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: 16, alignItems: "center" }}>
        <div>
          <p style={{ color: C.teal, fontSize: 11, textTransform: "uppercase", letterSpacing: ".12em", margin: 0 }}>
            Today · sample workspace
          </p>
          <h2 style={{ color: C.paper, fontSize: 22, margin: "5px 0 0" }}>What needs attention</h2>
        </div>
        <span style={{ ...mono, color: C.gold, fontSize: 12 }}>Growth &amp; income ▾</span>
      </div>
      <div style={{ display: "flex", gap: 7, margin: "18px 0 14px", flexWrap: "wrap" }}>
        {["Today", "Analyze", "Research", "Copilot"].map((item, index) => (
          <span
            key={item}
            style={{
              borderRadius: 999,
              border: `1px solid ${index === 0 ? C.teal : C.hair}`,
              background: index === 0 ? C.surfaceFaint : "transparent",
              color: index === 0 ? C.paper : C.slate,
              padding: "6px 10px",
              fontSize: 11,
            }}
          >
            {item}
          </span>
        ))}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
        {priorities.map(([label, detail, action], index) => (
          <div
            key={label}
            style={{
              display: "grid",
              gridTemplateColumns: "minmax(0,1fr) auto",
              gap: 14,
              alignItems: "center",
              borderRadius: 12,
              border: `1px solid ${C.hair}`,
              background: C.surfaceFaint,
              padding: "12px 13px",
            }}
          >
            <div style={{ minWidth: 0 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span
                  aria-hidden="true"
                  style={{
                    width: 7,
                    height: 7,
                    borderRadius: 999,
                    background: index === 0 ? C.down : index === 1 ? C.gold : C.teal,
                  }}
                />
                <strong style={{ color: C.paper, fontSize: 13 }}>{label}</strong>
              </div>
              <p style={{ color: C.slate, fontSize: 12, margin: "4px 0 0 15px" }}>{detail}</p>
            </div>
            <span style={{ color: C.teal, fontSize: 11, whiteSpace: "nowrap" }}>{action} →</span>
          </div>
        ))}
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 10,
          marginTop: 12,
        }}
      >
        <div style={{ borderRadius: 11, background: C.surfaceFaint, padding: 11 }}>
          <div style={{ color: C.slate, fontSize: 10 }}>HEALTH SCORE</div>
          <div style={{ ...mono, color: C.gold, fontSize: 20, marginTop: 2 }}>612 / 1000</div>
        </div>
        <div style={{ borderRadius: 11, background: C.surfaceFaint, padding: 11 }}>
          <div style={{ color: C.slate, fontSize: 10 }}>TEST SAFETY</div>
          <div style={{ color: C.paper, fontSize: 13, marginTop: 5 }}>0 holdings changed</div>
        </div>
      </div>
    </div>
  );
}
