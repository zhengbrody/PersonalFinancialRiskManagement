"use client";

/**
 * Pre-flight quota visibility: metered users see how many AI credits remain
 * BEFORE they type a question or run a verdict — not via a surprise 429
 * after the work is half-done. Hidden for unlimited (owner) plans, anonymous
 * visitors, and while billing is still loading.
 */

import Link from "next/link";
import { isBillingEnabled } from "@/lib/billing-flag";
import { useBillingMe } from "@/lib/queries";

export function CreditsBadge({ className }: { className?: string }) {
  const billing = useBillingMe();
  const credits = billing.data?.credits;
  if (!isBillingEnabled()) return null; // free beta: no credit meter
  if (
    !credits ||
    credits.unlimited ||
    credits.credits_total == null ||
    credits.credits_remaining == null
  ) {
    return null;
  }
  const remaining = Math.max(0, Math.floor(credits.credits_remaining));
  const low = credits.credits_total > 0 && remaining <= credits.credits_total * 0.2;
  return (
    <p className={`text-xs text-muted-foreground ${className ?? ""}`}>
      {remaining === 0 ? (
        <>
          You&apos;re out of AI credits this month.{" "}
          <Link href="/pricing" className="text-primary hover:underline">
            See plans
          </Link>{" "}
          to keep going — deterministic data stays free.
        </>
      ) : (
        <>
          {remaining} AI credit{remaining === 1 ? "" : "s"} left this month
          {low && (
            <>
              {" "}
              ·{" "}
              <Link href="/pricing" className="text-primary hover:underline">
                see plans
              </Link>
            </>
          )}
        </>
      )}
    </p>
  );
}
