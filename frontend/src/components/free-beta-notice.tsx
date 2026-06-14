/**
 * Shown in place of billing/pricing UI while the product runs as a free beta
 * (NEXT_PUBLIC_BILLING_ENABLED=false). Pure copy — no Stripe, no CTAs.
 */

import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { FREE_BETA_BODY, FREE_BETA_TITLE } from "@/lib/billing-flag";

export function FreeBetaNotice({ className }: { className?: string }) {
  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle className="text-base">{FREE_BETA_TITLE}</CardTitle>
        <CardDescription>{FREE_BETA_BODY}</CardDescription>
      </CardHeader>
    </Card>
  );
}
