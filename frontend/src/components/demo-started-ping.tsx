"use client";

import { useEffect } from "react";
import { track } from "@/lib/analytics";

/**
 * Fires the `demo_started` analytics event once when the /demo page mounts.
 * Safe event: no tickers, no $, no portfolio data — just "a demo was opened".
 */
export function DemoStartedPing() {
  useEffect(() => {
    track("demo_started", { source: "demo_page" });
  }, []);
  return null;
}
