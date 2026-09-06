import type { PortfolioMetrics } from "@/lib/schemas";

/** Presentation only. Never substitute gross assets for unavailable net equity. */
export function RiskSnapshot({
  metrics,
}: {
  metrics: Partial<PortfolioMetrics>;
}) {
  const available = (n: unknown): n is number =>
    typeof n === "number" && Number.isFinite(n);
  const cells = [
    {
      label: "Net equity",
      value: available(metrics.net_equity)
        ? new Intl.NumberFormat("en-US", {
            style: "currency",
            currency: "USD",
            maximumFractionDigits: 0,
          }).format(metrics.net_equity)
        : "Unavailable",
      note: "After margin borrowing",
    },
    {
      label: "Annualized volatility",
      value: available(metrics.annual_volatility)
        ? `${(metrics.annual_volatility * 100).toFixed(1)}%`
        : "Unavailable",
      note: "Historical current-mix variability",
    },
    {
      label: "Leverage",
      value: available(metrics.leverage)
        ? `${metrics.leverage.toFixed(2)}×`
        : "Unavailable",
      note: "Exposure relative to equity",
    },
  ];
  return (
    <dl
      className="grid gap-px overflow-hidden rounded-2xl border border-border bg-border sm:grid-cols-3"
      aria-label="Portfolio risk snapshot"
    >
      {cells.map((cell) => (
        <div key={cell.label} className="min-w-0 bg-card p-5 sm:p-6">
          <dt className="text-sm text-muted-foreground">{cell.label}</dt>
          <dd className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">
            {cell.value}
          </dd>
          <dd className="mt-1 text-xs leading-relaxed text-muted-foreground">
            {cell.note}
          </dd>
        </div>
      ))}
    </dl>
  );
}
