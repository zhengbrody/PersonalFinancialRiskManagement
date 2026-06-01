"use client";

/**
 * Home — an auth switch:
 *   signed-in  → personalized <Dashboard/> (the retention hook)
 *   anonymous  → <MarketingLanding/> (the story / signup funnel)
 *
 * Both render inside the SiteShell from the root layout.
 */

import { Dashboard } from "@/components/dashboard";
import { MarketingLanding } from "@/components/marketing-landing";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/lib/auth-context";

export default function Home() {
  const { user, loading, configured } = useAuth();

  // Avoid flashing the marketing page before the session resolves.
  if (configured && loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  if (configured && user) return <Dashboard />;
  return <MarketingLanding />;
}
