"use client";

/**
 * Mobile hamburger for the marketing nav. The desktop inline links
 * (.mm-nav-links) hide <640px with no replacement; this fills that gap with a
 * ☰ button (.mm-mobile-nav, shown only <640px via globals.css) that opens a
 * full-screen overlay listing the shared NAV_LINKS + the auth CTAs. Closes on
 * route change and locks body scroll while open.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { C } from "./theme";
import { NAV_LINKS } from "./nav-links";

export function MobileNav({ signedIn }: { signedIn: boolean }) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  // Close on navigation.
  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  // Lock body scroll while the overlay is open.
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  return (
    <>
      <button
        type="button"
        className="mm-mobile-nav"
        aria-label={open ? "Close menu" : "Open menu"}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        style={{
          alignItems: "center",
          justifyContent: "center",
          width: 40,
          height: 40,
          borderRadius: 10,
          background: "transparent",
          border: `1px solid ${C.hairStrong}`,
          color: C.paper,
          fontSize: 18,
          cursor: "pointer",
        }}
      >
        {open ? "✕" : "☰"}
      </button>

      {open && (
        <div
          role="dialog"
          aria-modal="true"
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 60,
            background: C.ink,
            display: "flex",
            flexDirection: "column",
            padding: "92px 28px 40px",
            gap: 6,
          }}
        >
          {NAV_LINKS.map(([label, href]) => (
            <Link
              key={href}
              href={href}
              onClick={() => setOpen(false)}
              style={{
                color: C.paper,
                fontSize: 20,
                fontWeight: 500,
                padding: "16px 8px",
                borderBottom: `1px solid ${C.hair}`,
                textDecoration: "none",
              }}
            >
              {label}
            </Link>
          ))}

          <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 24 }}>
            {signedIn ? (
              <Link href="/" onClick={() => setOpen(false)} style={primaryBtn}>
                Open dashboard
              </Link>
            ) : (
              <>
                <Link href="/signup" onClick={() => setOpen(false)} style={primaryBtn}>
                  Get started — free
                </Link>
                <Link href="/login" onClick={() => setOpen(false)} style={ghostBtn}>
                  Sign in
                </Link>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}

const primaryBtn = {
  textAlign: "center" as const,
  padding: "16px",
  borderRadius: 12,
  background: C.ctaBg,
  color: C.ctaFg,
  fontSize: 16,
  fontWeight: 600,
  textDecoration: "none",
};

const ghostBtn = {
  textAlign: "center" as const,
  padding: "16px",
  borderRadius: 12,
  background: "transparent",
  color: C.paper,
  border: `1px solid ${C.hairStrong}`,
  fontSize: 16,
  fontWeight: 600,
  textDecoration: "none",
};
