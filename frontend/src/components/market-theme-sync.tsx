"use client";

/**
 * Keeps the `.dark` class on <html> in sync with the day/night session
 * *while the tab is open*, so the theme flips on its own at the 04:00 / 20:00
 * ET boundaries without a reload.
 *
 * The INITIAL theme is set flash-free by the inline boot script in
 * `app/layout.tsx` (runs before paint). This component only handles the
 * live transitions afterwards: a coarse 60s poll (the boundary only moves
 * twice a day, so sub-minute precision is pointless) plus an immediate
 * re-check when the user refocuses the tab after it was backgrounded.
 *
 * Renders nothing.
 */

import { useEffect } from "react";
import { marketTheme } from "@/lib/market-hours";

function apply() {
  const dark = marketTheme() === "dark";
  const root = document.documentElement;
  root.classList.toggle("dark", dark);
  // Keep native UI (scrollbars, form controls) matched to the theme.
  root.style.colorScheme = dark ? "dark" : "light";
}

export function MarketThemeSync() {
  useEffect(() => {
    apply(); // reconcile once on mount (in case the boot script was skipped)
    const id = window.setInterval(apply, 60_000);
    const onVisible = () => {
      if (document.visibilityState === "visible") apply();
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", apply);
    return () => {
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", apply);
    };
  }, []);

  return null;
}
