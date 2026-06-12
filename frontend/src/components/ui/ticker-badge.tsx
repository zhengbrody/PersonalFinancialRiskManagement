/**
 * Terminal-style ticker chip — mono, bordered, fixed-width digits. One
 * shared look for every symbol the UI renders inside tables/lists, so
 * tickers read as instruments (not prose) across the platform.
 */

import { cn } from "@/lib/utils";

export function TickerBadge({
  ticker,
  className,
}: {
  ticker: string;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-block rounded border border-border bg-muted/50 px-1.5 py-0.5 font-mono text-[11px] font-medium leading-none tracking-wide",
        className,
      )}
    >
      {ticker}
    </span>
  );
}
