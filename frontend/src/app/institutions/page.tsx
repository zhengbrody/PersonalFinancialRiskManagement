"use client";

/**
 * /institutions — SEC 13F "smart money" (Phase: legacy 8_Institutions port).
 * Authed: shows institutional conviction in the user's holdings + a fund
 * deep-dive. Free SEC EDGAR data, fail-soft server-side.
 */

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Skeleton } from "@/components/ui/skeleton";
import { InstitutionDeepDive, SmartMoneySignals } from "@/components/smart-money";
import { useAuth } from "@/lib/auth-context";
import { authHref } from "@/lib/auth-redirect";

export default function InstitutionsPage() {
  const router = useRouter();
  const { user, loading, configured } = useAuth();

  useEffect(() => {
    if (!configured) return;
    if (!loading && !user) {
      router.replace(authHref("/login", "/institutions"));
    }
  }, [user, loading, configured, router]);

  if (!configured || loading || !user) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-12 w-64" />
        <Skeleton className="h-40" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-3xl font-semibold tracking-tight">Smart money</h1>
        <p className="text-sm text-muted-foreground">
          What the big institutional funds are holding — and what they bought or
          sold last quarter — from their SEC 13F filings.
        </p>
      </header>

      <SmartMoneySignals />
      <InstitutionDeepDive />
    </div>
  );
}
