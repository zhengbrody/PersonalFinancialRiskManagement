import { type ReactNode } from "react";
import { MarketingShell } from "./marketing-shell";
import { C, display } from "./theme";
import styles from "./public-experience.module.css";

/**
 * Shared auth scaffold: a product introduction beside the desktop form;
 * form-first on mobile. Existing auth and safe redirect behavior stay in pages.
 */
export function AuthShell({
  title,
  subtitle,
  highlights,
  footer,
  children,
}: {
  title: string;
  subtitle?: ReactNode;
  highlights?: readonly string[];
  footer?: ReactNode;
  children: ReactNode;
}) {
  return (
    <MarketingShell minimal>
      <div className={styles.authLayout}>
        <aside className={styles.authIntro}>
          <p className={styles.eyebrow}>Clarity before action</p>
          <h2>Understand your risk.<br />Keep the decision yours.</h2>
          <p>Inspect your portfolio, test a hypothetical change, and keep the evidence behind your plan.</p>
          <a className={styles.link} href="/demo-risk-check">Explore a sample first →</a>
          <p className={styles.hint}>No trades placed. Tests do not change real holdings.</p>
        </aside>
        <div>
        <div style={{ textAlign: "center", marginBottom: 26 }}>
          <h1
            style={{
              ...display,
              fontWeight: 400,
              fontSize: "clamp(34px,5vw,46px)",
              lineHeight: 1.05,
              letterSpacing: "-0.01em",
              color: C.paper,
              margin: "0 0 10px",
            }}
          >
            {title}
          </h1>
          {subtitle && <p style={{ color: C.slate, fontSize: 15, margin: 0 }}>{subtitle}</p>}
        </div>
        <div
          style={{
            borderRadius: 18,
            border: `1px solid ${C.hair}`,
            background: C.cardGrad,
            padding: 26,
          }}
        >
          {children}
        </div>
        {highlights && highlights.length > 0 && (
          <div
            style={{
              display: "grid",
              gap: 8,
              marginTop: 18,
              borderRadius: 14,
              border: `1px solid ${C.hair}`,
              background: C.surfaceFaint,
              padding: "14px 16px",
            }}
          >
            {highlights.map((item, index) => (
              <div key={item} style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                <span style={{ color: C.teal, fontSize: 12, marginTop: 2 }}>{index + 1}</span>
                <span style={{ color: C.slate, fontSize: 13, lineHeight: 1.45 }}>{item}</span>
              </div>
            ))}
          </div>
        )}
        {footer && (
          <p style={{ textAlign: "center", marginTop: 18, fontSize: 14, color: C.slate }}>{footer}</p>
        )}
        </div>
      </div>
    </MarketingShell>
  );
}
