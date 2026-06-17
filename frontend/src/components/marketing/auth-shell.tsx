import { type ReactNode } from "react";
import { MarketingShell } from "./marketing-shell";
import { C, display } from "./theme";

/**
 * Centered auth-page scaffold (login / signup): the minimal dark MarketingShell
 * + a serif title + subtitle + a hairline card holding the form + an optional
 * footer line. One source for the auth chrome so the two pages stay identical
 * except for their form + copy.
 */
export function AuthShell({
  title,
  subtitle,
  footer,
  children,
}: {
  title: string;
  subtitle?: ReactNode;
  footer?: ReactNode;
  children: ReactNode;
}) {
  return (
    <MarketingShell minimal>
      <div style={{ maxWidth: 440, margin: "0 auto", padding: "150px 24px 90px" }}>
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
        {footer && (
          <p style={{ textAlign: "center", marginTop: 18, fontSize: 14, color: C.slate }}>{footer}</p>
        )}
      </div>
    </MarketingShell>
  );
}
