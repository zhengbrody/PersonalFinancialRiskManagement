"use client";

/**
 * Full-bleed chrome for every pre-login marketing/content surface: the premium
 * dark background + a fixed, scroll-aware, auth-aware top nav + a footer with
 * site links. Pages render their own sections inside; SiteShell renders these
 * routes bare (no app header) so this owns the viewport.
 *
 * `minimal` (auth pages): logo-only nav + a slim footer — no nav links / CTAs.
 */

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { Logo } from "@/components/ui/logo";
import { useAuth } from "@/lib/auth-context";
import { LEGAL_DOCS } from "@/lib/legal-content";
import { C } from "./theme";
import { CTA } from "./primitives";
import { MobileNav } from "./mobile-nav";
import { NAV_LINKS } from "./nav-links";

export function MarketingShell({
  children,
  minimal = false,
}: {
  children: ReactNode;
  minimal?: boolean;
}) {
  return (
    // No forced `dark` class — the marketing palette (--mm-*) flips with the
    // app's market-synced `.dark` on <html>, so pre-login is light during the
    // trading day and dark overnight, just like the signed-in product.
    <div
      style={{
        background: C.ink,
        color: C.paper,
        fontFamily: "var(--font-geist-sans, system-ui, sans-serif)",
        overflowX: "hidden",
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <MarketingNav minimal={minimal} />
      <div style={{ flex: 1 }}>{children}</div>
      <MarketingFooter minimal={minimal} />
    </div>
  );
}

function Wordmark({ size = 26 }: { size?: number }) {
  return (
    <Link
      href="/"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        fontWeight: 600,
        fontSize: 15,
        color: C.paper,
        textDecoration: "none",
        letterSpacing: "-0.02em",
      }}
    >
      <Logo size={size} />
      MindMarket
    </Link>
  );
}

function MarketingNav({ minimal }: { minimal: boolean }) {
  const { user, configured } = useAuth();
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  const signedIn = configured && !!user;

  return (
    <nav
      style={{
        position: "fixed",
        insetInline: 0,
        top: 0,
        zIndex: 50,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: scrolled ? "12px 32px" : "16px 32px",
        background: scrolled ? C.navBg : "transparent",
        backdropFilter: scrolled ? "blur(14px)" : "none",
        borderBottom: `1px solid ${scrolled ? C.hair : "transparent"}`,
        transition: "all .3s",
      }}
    >
      <Wordmark />
      {minimal ? (
        <Link href="/" style={{ color: C.slate, fontSize: 14, textDecoration: "none" }}>
          ← Back to site
        </Link>
      ) : (
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div className="mm-nav-links" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {NAV_LINKS.map(([l, href]) => (
              <Link
                key={href}
                href={href}
                style={{
                  color: C.slate,
                  fontSize: 14,
                  padding: "8px 14px",
                  borderRadius: 8,
                  textDecoration: "none",
                }}
              >
                {l}
              </Link>
            ))}
          </div>
          {signedIn ? (
            <CTA href="/">Open Today</CTA>
          ) : (
            <>
              <CTA variant="ghost" href="/login">
                Sign in
              </CTA>
              <CTA href="/signup">Get started</CTA>
            </>
          )}
          {/* Mobile hamburger — visible <640px where .mm-nav-links collapses. */}
          <MobileNav signedIn={signedIn} />
        </div>
      )}
    </nav>
  );
}

function MarketingFooter({ minimal }: { minimal: boolean }) {
  // Explore links only — the nav owns the Sign in / Get started actions.
  const links: [string, string][] = [
    ["Product", "/product"],
    ["Workflow", "/product#workflow"],
    ["Learn", "/learn"],
    ["Methodology", "/methodology/health-score"],
    ["Resources", "/resources"],
    ["Markets", "/markets"],
    ["Risk Signal", "/risk-today"],
    ["Demo", "/demo-risk-check"],
  ];
  return (
    <footer style={{ padding: "48px 32px 60px", borderTop: `1px solid ${C.hair}` }}>
      <div style={{ maxWidth: 1100, margin: "0 auto", display: "flex", flexDirection: "column", gap: 20 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flexWrap: "wrap",
            gap: 18,
          }}
        >
          <Wordmark size={24} />
          {!minimal && (
            <nav className="mm-footer-links" style={{ display: "flex", flexWrap: "wrap", gap: 18, fontSize: 14 }}>
              {links.map(([l, href]) => (
                <Link key={href} href={href} style={{ color: C.slate, textDecoration: "none" }}>
                  {l}
                </Link>
              ))}
            </nav>
          )}
        </div>
        <p style={{ fontSize: 12.5, color: C.slateDim, maxWidth: "60em", lineHeight: 1.5, margin: 0 }}>
          MindMarket provides educational portfolio analytics and software demonstrations. It does
          not provide investment, tax, legal, or financial advice. Interactive demos use clearly
          labeled sample books; public market pages may use source-stamped live macro data.
        </p>
        <nav style={{ display: "flex", flexWrap: "wrap", gap: 16, fontSize: 12.5 }}>
          {LEGAL_DOCS.map((d) => (
            <Link key={d.slug} href={`/legal/${d.slug}`} style={{ color: C.slate, textDecoration: "none" }}>
              {d.nav}
            </Link>
          ))}
        </nav>
      </div>
    </footer>
  );
}
