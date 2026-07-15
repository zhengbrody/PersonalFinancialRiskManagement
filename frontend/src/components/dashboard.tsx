"use client";

/**
 * The signed-in home. `/` is an auth switch (see app/page.tsx): signed-in →
 * this, anonymous → the marketing landing. The dashboard is now the **Today**
 * action center — a focused "what to look at next" surface, not a long report.
 * This thin wrapper preserves the acquisition-funnel events (score_viewed /
 * first_score_completed) fired off the shared active-score query; Today owns
 * the UI.
 */

import { useEffect, useRef } from "react";
import { Today } from "@/components/today";
import { track } from "@/lib/analytics";
import { ANALYTICS_EVENTS } from "@/lib/analytics-events";
import { useActiveScore } from "@/lib/queries";

export function Dashboard() {
  // Shared cached query (Today reads the same one — no double fetch); used here
  // only to fire the once-per-score funnel events.
  const score = useActiveScore();
  const tracked = useRef<number | null>(null);
  useEffect(() => {
    if (score.data && tracked.current !== score.data.overall_score) {
      tracked.current = score.data.overall_score;
      track("score_viewed", { overall_score: Math.round(score.data.overall_score) });
      try {
        if (!window.localStorage.getItem("mm_first_score")) {
          window.localStorage.setItem("mm_first_score", "1");
          track(ANALYTICS_EVENTS.first_score_completed);
        }
      } catch {
        /* storage unavailable */
      }
    }
  }, [score.data]);

  return <Today />;
}
