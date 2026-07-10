"use client";

/**
 * /settings — weekly risk digest toggle. Default is ON (opt-out model, the
 * email itself carries a one-click unsubscribe). Fail-soft: while the 0007
 * tables aren't applied the GET errors → we render nothing rather than a
 * broken toggle.
 */

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useDigestPref, useSetDigestPref } from "@/lib/queries";

export function WeeklyDigestCard() {
  const pref = useDigestPref();
  const setPref = useSetDigestPref();

  if (pref.isError) return null;
  const enabled = pref.data?.enabled ?? false; // opt-in: off unless explicitly enabled

  return (
    <Card>
      <CardHeader>
        <CardTitle>Weekly risk digest</CardTitle>
        <CardDescription>
          Optional — off by default. Opt in to get one email every Monday morning:
          your Health Score changes, volatility, concentration, and market state — all
          from the deterministic numbers of your own most recent score. Educational
          content; unsubscribe anytime with one click.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm">
          Status:{" "}
          <span className={enabled ? "font-medium text-[hsl(var(--success))]" : "text-muted-foreground"}>
            {pref.isLoading ? "…" : enabled ? "Enabled" : "Disabled"}
          </span>
        </p>
        <Button
          variant={enabled ? "outline" : "default"}
          size="sm"
          disabled={pref.isLoading || setPref.isPending}
          onClick={() => setPref.mutate(!enabled)}
        >
          {setPref.isPending ? "Saving…" : enabled ? "Turn off digest" : "Turn on digest"}
        </Button>
        {setPref.isError && (
          <p className="w-full text-xs text-destructive">Save failed, please try again later.</p>
        )}
      </CardContent>
    </Card>
  );
}
