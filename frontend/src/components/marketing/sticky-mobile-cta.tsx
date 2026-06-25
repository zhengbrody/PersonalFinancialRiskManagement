"use client";

/**
 * Sticky bottom CTA bar for the anon marketing landing (mobile only). Shown
 * <640px via the .mm-sticky-cta class (globals.css); hidden for signed-in users.
 * Keeps the primary "try the demo / get started" action one tap away during a
 * long scroll — the biggest mobile conversion lever the audit flagged missing.
 */

import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { track } from "@/lib/analytics";
import { C } from "./theme";

export function StickyMobileCTA() {
  const { user, configured } = useAuth();
  if (configured && user) return null; // signed-in users don't need a signup bar

  return (
    <div
      className="mm-sticky-cta"
      style={{
        position: "fixed",
        insetInline: 0,
        bottom: 0,
        zIndex: 55,
        gap: 10,
        padding: "12px 16px calc(12px + env(safe-area-inset-bottom))",
        background: C.navBg,
        backdropFilter: "blur(14px)",
        borderTop: `1px solid ${C.hairStrong}`,
      }}
    >
      <Link
        href="/demo-risk-check"
        onClick={() => track("sticky_cta_clicked", { target: "demo" })}
        style={{
          flex: 2,
          textAlign: "center",
          padding: "13px",
          borderRadius: 11,
          background: C.ctaBg,
          color: C.ctaFg,
          fontSize: 15,
          fontWeight: 600,
          textDecoration: "none",
        }}
      >
        Try a free risk check
      </Link>
      <Link
        href="/signup"
        onClick={() => track("sticky_cta_clicked", { target: "signup" })}
        style={{
          flex: 1,
          textAlign: "center",
          padding: "13px",
          borderRadius: 11,
          background: "transparent",
          color: C.paper,
          border: `1px solid ${C.hairStrong}`,
          fontSize: 15,
          fontWeight: 600,
          textDecoration: "none",
        }}
      >
        Sign up
      </Link>
    </div>
  );
}
