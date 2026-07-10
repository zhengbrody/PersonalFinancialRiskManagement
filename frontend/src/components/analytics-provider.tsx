"use client";

/**
 * Mounts PostHog: inits once, identifies the signed-in user (and resets on
 * sign-out), and captures a pageview on every App-Router navigation (manual,
 * since the SPA router doesn't fire native page loads). Renders nothing.
 * No-op entirely when analytics are disabled (dev/test/no key).
 */

import { Suspense, useEffect, useRef } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import {
  capturePageview,
  identifyUser,
  initAnalytics,
  resetAnalytics,
} from "@/lib/analytics";

function PageviewTracker() {
  const pathname = usePathname();
  const search = useSearchParams();
  useEffect(() => {
    if (!pathname) return;
    const qs = search?.toString();
    capturePageview(
      window.location.origin + pathname + (qs ? `?${qs}` : ""),
    );
  }, [pathname, search]);
  return null;
}

export function AnalyticsProvider() {
  const { user } = useAuth();
  const identified = useRef<string | null>(null);

  useEffect(() => {
    initAnalytics();
  }, []);

  useEffect(() => {
    const uid = user?.id ?? null;
    if (uid && identified.current !== uid) {
      identified.current = uid;
      // Privacy: identify with the Supabase UUID ONLY — email (or any other
      // person property) never leaves the browser for PostHog.
      identifyUser(uid);
    } else if (!uid && identified.current) {
      identified.current = null;
      resetAnalytics(); // sign-out → unlink the anonymous session
    }
  }, [user?.id]);

  // useSearchParams must sit under a Suspense boundary in the App Router.
  return (
    <Suspense fallback={null}>
      <PageviewTracker />
    </Suspense>
  );
}
