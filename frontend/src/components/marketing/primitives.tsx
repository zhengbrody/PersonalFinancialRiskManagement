/**
 * Presentational marketing primitives on the shared dark palette. No hooks /
 * browser APIs → server-safe, so the content pages (/product, /learn, …) stay
 * server components (fully crawlable) while still wearing the premium look.
 * Colours are inline literals from theme.ts (forced-dark, theme-independent).
 */

import Link from "next/link";
import { type CSSProperties, type ReactNode } from "react";
import { Icon, type IconName } from "@/components/ui/icon";
import { C, display, eyebrow as eyebrowStyle, secTitle, bodyText } from "./theme";

/* Button — internal routes → next/link, in-page anchors / external → <a>. */
export function CTA({
  children,
  variant = "primary",
  href = "#",
  lg,
  onClick,
}: {
  children: ReactNode;
  variant?: "primary" | "ghost";
  href?: string;
  lg?: boolean;
  onClick?: () => void;
}) {
  const base: CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    fontWeight: 500,
    borderRadius: lg ? 12 : 10,
    height: lg ? 52 : 44,
    padding: lg ? "0 28px" : "0 20px",
    fontSize: lg ? 16 : 15,
    border: "1px solid transparent",
    cursor: "pointer",
    transition: "transform .15s, box-shadow .25s, background .2s",
    whiteSpace: "nowrap",
    textDecoration: "none",
  };
  const v =
    variant === "primary"
      ? { background: C.ctaBg, color: C.ctaFg, boxShadow: "0 10px 30px -10px rgba(212,160,23,.35)" }
      : { background: C.surfaceFaint, color: C.paper, borderColor: C.hairStrong };
  const style = { ...base, ...v };
  if (href.startsWith("/")) {
    return (
      <Link href={href} style={style} onClick={onClick}>
        {children}
      </Link>
    );
  }
  return (
    <a href={href} style={style} onClick={onClick}>
      {children}
    </a>
  );
}

/* Full-width section with a top hairline + centered container. */
export function Band({ children, id }: { children: ReactNode; id?: string }) {
  return (
    <section id={id} style={{ borderTop: `1px solid ${C.hair}` }}>
      <div style={{ maxWidth: 1100, margin: "0 auto", padding: "84px 32px" }}>{children}</div>
    </section>
  );
}

export function Eyebrow({ children }: { children: ReactNode }) {
  return <p style={eyebrowStyle}>{children}</p>;
}

export function SecTitle({ children }: { children: ReactNode }) {
  return <h2 style={secTitle}>{children}</h2>;
}

/** Italic gold emphasis used inside headlines (the editorial accent). */
export function Em({ children }: { children: ReactNode }) {
  return <em style={{ fontStyle: "italic", color: C.gold }}>{children}</em>;
}

/* Page header: eyebrow + serif H1 + lede, with top padding clearing the fixed nav. */
export function MarketingHero({
  eyebrow,
  title,
  lede,
  children,
}: {
  eyebrow: string;
  title: ReactNode;
  lede?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header style={{ maxWidth: 1100, margin: "0 auto", padding: "128px 32px 12px" }}>
      <p style={eyebrowStyle}>{eyebrow}</p>
      <h1
        style={{
          ...display,
          fontWeight: 400,
          fontSize: "clamp(38px,5vw,64px)",
          lineHeight: 1.04,
          letterSpacing: "-0.01em",
          margin: "0 0 20px",
          color: C.paper,
        }}
      >
        {title}
      </h1>
      {lede && (
        <p style={{ ...bodyText, fontSize: "clamp(16px,1.5vw,19px)", maxWidth: "42em" }}>{lede}</p>
      )}
      {children}
    </header>
  );
}

/* Hairline gradient card. With href → a link (hover via .mm-card in globals.css). */
export function MarketingCard({
  href,
  children,
  className,
}: {
  href?: string;
  children: ReactNode;
  className?: string;
}) {
  const style: CSSProperties = {
    display: "block",
    borderRadius: 16,
    border: `1px solid ${C.hair}`,
    background: C.cardGrad,
    padding: 22,
    height: "100%",
    textDecoration: "none",
    color: "inherit",
  };
  const cls = ["mm-card", className].filter(Boolean).join(" ");
  if (href) {
    if (href.startsWith("/")) {
      return (
        <Link href={href} style={style} className={cls}>
          {children}
        </Link>
      );
    }
    return (
      <a href={href} style={style} className={cls}>
        {children}
      </a>
    );
  }
  return (
    <div style={style} className={className}>
      {children}
    </div>
  );
}

/* Teal gradient tile holding a monoline icon with an ink stroke. */
export function IconChip({ name, size = 46 }: { name: IconName; size?: number }) {
  return (
    <div
      style={{
        width: size,
        height: size,
        borderRadius: 12,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: `linear-gradient(135deg, ${C.teal}, ${C.tealDeep})`,
        boxShadow: "0 8px 20px -8px rgba(47,167,188,.5)",
      }}
    >
      <Icon name={name} style={{ width: size * 0.5, height: size * 0.5, color: "#06151c" }} />
    </div>
  );
}

/* Small print (educational disclaimer / footnote). */
export function Disclaimer({ children }: { children: ReactNode }) {
  return (
    <p style={{ fontSize: 12.5, color: C.slateDim, lineHeight: 1.55, margin: 0 }}>{children}</p>
  );
}

/* Row CTA panel — headline + lede on the left, action buttons on the right.
   The shared "convert here" card used at the foot of the content pages. */
export function CTABox({
  headline,
  lede,
  children,
}: {
  headline: ReactNode;
  lede?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        flexWrap: "wrap",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 18,
        borderRadius: 18,
        border: `1px solid ${C.hair}`,
        background: C.cardGrad,
        padding: "24px 26px",
      }}
    >
      <div>
        <p style={{ fontWeight: 600, fontSize: 17, margin: 0, color: C.paper }}>{headline}</p>
        {lede && (
          <p style={{ fontSize: 14, color: C.slate, margin: "4px 0 0", maxWidth: "42em" }}>{lede}</p>
        )}
      </div>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>{children}</div>
    </div>
  );
}
