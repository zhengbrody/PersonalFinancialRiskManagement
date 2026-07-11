"use client";

/**
 * Sticky bottom CTA bar for the anon marketing landing (mobile only). Shown
 * <640px via the .mm-sticky-cta class (globals.css); hidden for signed-in users.
 * Keeps the primary "try the demo / get started" action one tap away during a
 * long scroll — the biggest mobile conversion lever the audit flagged missing.
 */

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { track } from "@/lib/analytics";
import { C } from "./theme";

export function StickyMobileCTA() {
  const { user, configured } = useAuth();
  const signedIn = Boolean(configured && user);
  // A bar that duplicates a CTA already on screen is noise — reveal it only once
  // the hero's primary CTA (marked `data-hero-cta`) has scrolled out of view.
  // Default hidden so SSR and hydration agree; a scroll threshold is the fallback
  // when the marker or IntersectionObserver is unavailable.
  const [pastHero, setPastHero] = useState(false);

  useEffect(() => {
    if (signedIn) return;
    const target = document.querySelector("[data-hero-cta]");
    if (target && "IntersectionObserver" in window) {
      const io = new IntersectionObserver(
        ([entry]) => setPastHero(!entry.isIntersecting),
      );
      io.observe(target);
      return () => io.disconnect();
    }
    const onScroll = () =>
      setPastHero(window.scrollY > window.innerHeight * 0.6);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [signedIn]);

  if (signedIn) return null; // signed-in users don't need a signup bar
  if (!pastHero) return null; // still looking at the first CTA

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
