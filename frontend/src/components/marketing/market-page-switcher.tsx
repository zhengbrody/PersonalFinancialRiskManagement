import Link from "next/link";
import type { CSSProperties } from "react";
import { C, display, eyebrow } from "./theme";

type MarketSurface = "signal" | "desk";

const SURFACES: Array<{
  id: MarketSurface;
  href: string;
  label: string;
  question: string;
  scope: string;
}> = [
  {
    id: "signal",
    href: "/risk-today",
    label: "Risk Today",
    question: "Is elevated volatility becoming more likely?",
    scope: "A model signal for roughly the next two weeks, with drivers, confidence, health, and limits.",
  },
  {
    id: "desk",
    href: "/markets",
    label: "Markets",
    question: "What is moving right now?",
    scope: "A live conditions desk for volatility, rates, sectors, macro releases, and market headlines.",
  },
];

/**
 * Makes the boundary between the two public market surfaces explicit. The
 * current view is a non-interactive card; the other view is the handoff link.
 */
export function MarketPageSwitcher({ active }: { active: MarketSurface }) {
  return (
    <section aria-labelledby="market-page-switcher-title">
      <p style={{ ...eyebrow, margin: "0 0 10px" }}>Two views · different jobs</p>
      <h2
        id="market-page-switcher-title"
        style={{
          ...display,
          color: C.paper,
          fontSize: "clamp(25px,3vw,34px)",
          fontWeight: 400,
          lineHeight: 1.12,
          margin: "0 0 22px",
        }}
      >
        Forecast the pressure. Read the tape.
      </h2>
      <div
        className="mm-market-page-grid"
        style={{ display: "grid", gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: 14 }}
      >
        {SURFACES.map((surface) => {
          const current = surface.id === active;
          const content = (
            <>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 12,
                }}
              >
                <span style={{ color: C.paper, fontSize: 17, fontWeight: 650 }}>{surface.label}</span>
                <span
                  style={{
                    color: current ? C.gold : C.teal,
                    fontSize: 11,
                    fontWeight: 700,
                    letterSpacing: "0.08em",
                    textTransform: "uppercase",
                  }}
                >
                  {current ? "You are here" : "Open →"}
                </span>
              </div>
              <p style={{ color: C.paper, fontSize: 15, fontWeight: 600, margin: "18px 0 7px" }}>
                {surface.question}
              </p>
              <p style={{ color: C.slate, fontSize: 13.5, lineHeight: 1.55, margin: 0 }}>
                {surface.scope}
              </p>
            </>
          );
          const style: CSSProperties = {
            display: "block",
            minHeight: 174,
            padding: 22,
            borderRadius: 16,
            border: `1px solid ${current ? `color-mix(in srgb, ${C.gold} 52%, transparent)` : C.hair}`,
            background: current
              ? `color-mix(in srgb, ${C.gold} 7%, ${C.ink})`
              : C.cardGrad,
            color: "inherit",
            textDecoration: "none",
          };

          return current ? (
            <div key={surface.id} aria-current="page" style={style}>
              {content}
            </div>
          ) : (
            <Link key={surface.id} href={surface.href} className="mm-card" style={style}>
              {content}
            </Link>
          );
        })}
      </div>
    </section>
  );
}
