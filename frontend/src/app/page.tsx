"use client";

/**
 * Home — an auth switch:
 *   signed-in  → personalized <Dashboard/> (the retention hook)
 *   anonymous  → <MarketingLanding/> (the story / signup funnel)
 *
 * Both render inside the SiteShell from the root layout.
 *
 * While the session resolves we render the MARKETING page by default and a
 * skeleton only when localStorage carries a Supabase session (a returning
 * user about to see the dashboard). Rendering marketing-by-default matters
 * for SEO: the production prerender runs with `loading=true`, so whatever
 * this branch returns is the landing HTML crawlers see — a skeleton here
 * shipped a content-free homepage (caught 2026-06-11). Anonymous visitors
 * also paint real content immediately instead of a skeleton.
 */

import { useEffect, useState } from "react";
import { Dashboard } from "@/components/dashboard";
import { MarketingLanding } from "@/components/marketing-landing";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/lib/auth-context";

/** True when localStorage holds a Supabase auth token (sb-<ref>-auth-token) —
 * a strong hint the visitor is signed in and the dashboard is coming. */
function hasStoredSession(): boolean {
  try {
    for (let i = 0; i < window.localStorage.length; i++) {
      const key = window.localStorage.key(i);
      if (key && key.startsWith("sb-") && key.includes("auth-token")) return true;
    }
  } catch {
    /* storage blocked → treat as anonymous */
  }
  return false;
}

export default function Home() {
  const { user, loading, configured } = useAuth();

  // Post-mount only (SSR has no localStorage; reading it during hydration
  // would mismatch the server HTML). Until mounted we show marketing.
  const [returningUser, setReturningUser] = useState(false);
  useEffect(() => {
    setReturningUser(hasStoredSession());
  }, []);

  if (configured && loading) {
    // Returning user: skeleton beats a marketing flash before the dashboard.
    if (returningUser) {
      return (
        <div className="space-y-6">
          <Skeleton className="h-8 w-64" />
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-48 w-full" />
        </div>
      );
    }
    return <MarketingLanding />;
  }

  if (configured && user) return <Dashboard />;
  return <MarketingLanding />;
}
