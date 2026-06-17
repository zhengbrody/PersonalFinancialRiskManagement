/**
 * Badge — small status / category pill (MindMarket design system,
 * components/data/Badge). Tones map to the semantic risk palette; soft tinted
 * fill with a matching low-alpha border, like the plan + provenance pills.
 *
 * For richer, multi-level status (e.g. the 4-level risk SeverityBadge) keep the
 * bespoke component — this is the generic single-tone pill.
 */

import { type ReactNode } from "react";
import { cn } from "@/lib/utils";

export type BadgeTone = "neutral" | "primary" | "success" | "warning" | "danger";

const TONE: Record<BadgeTone, string> = {
  neutral: "border-border bg-muted text-muted-foreground",
  primary: "border-primary/40 bg-primary/10 text-primary",
  success: "border-success/40 bg-success/10 text-success",
  warning: "border-warning/40 bg-warning/10 text-warning",
  danger: "border-destructive/40 bg-destructive/10 text-destructive",
};

export function Badge({
  tone = "neutral",
  uppercase = false,
  className,
  children,
}: {
  tone?: BadgeTone;
  uppercase?: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium leading-tight",
        uppercase && "uppercase tracking-wide",
        TONE[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
