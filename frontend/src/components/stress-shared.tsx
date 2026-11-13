"use client";

/**
 * Shared pieces for the Quant Lab risk panels (Stress Lab, Crisis replay,
 * Model validation): theme-token colours, number formatting, a segmented
 * control and a chart tooltip. Formatting only — no figure is computed here.
 */

export const LOSS = "hsl(var(--destructive))";
export const GAIN = "hsl(var(--success))";
export const INK = "hsl(var(--primary))";
export const AXIS = "hsl(var(--muted-foreground))";
export const NEUTRAL = "hsl(var(--foreground) / 0.55)";
export const GRID = "hsl(var(--border))";

export const SHORT: Record<string, string> = {
  equity: "Equity",
  rates: "Rates",
  credit: "Credit",
  usd: "Dollar",
  oil: "Oil",
  vol: "Vol",
  gold: "Gold",
};

export const usd = (v: number) =>
  `${v < 0 ? "−" : ""}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
export const pct = (v: number, d = 1) => `${v < 0 ? "−" : ""}${Math.abs(v * 100).toFixed(d)}%`;
export const signedPct = (v: number, d = 1) => {
  const text = Math.abs(v * 100).toFixed(d);
  // A value that rounds to zero carries no sign ("−0%" reads as a number).
  return Number(text) === 0 ? `${text}%` : `${v > 0 ? "+" : "−"}${text}%`;
};
/** Compact dollars for tight tiles: −$28.0k, $1.2M. */
export const usdShort = (v: number) => {
  const a = Math.abs(v);
  const body = a >= 1e6 ? `${(a / 1e6).toFixed(2)}M` : a >= 1e4 ? `${(a / 1e3).toFixed(1)}k` : a.toLocaleString(undefined, { maximumFractionDigits: 0 });
  return `${v < 0 ? "−" : ""}$${body}`;
};
export const dayTick = (iso: string) => {
  const d = new Date(`${iso}T00:00:00`);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "2-digit" });
};

export function Seg<T extends string | number | boolean>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-muted-foreground">{label}</span>
      <div role="group" aria-label={label} className="inline-flex rounded-md border border-border p-0.5">
        {options.map((o) => (
          <button
            key={String(o.value)}
            type="button"
            aria-pressed={o.value === value}
            onClick={() => onChange(o.value)}
            className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
              o.value === value
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export function Tip({ rows }: { rows: [string, string][] }) {
  return (
    <div className="rounded-md border border-border bg-card px-3 py-2 text-xs shadow-sm">
      {rows.map(([k, v]) => (
        <p key={k} className="flex justify-between gap-4">
          <span className="text-muted-foreground">{k}</span>
          <span className="font-mono font-medium text-foreground">{v}</span>
        </p>
      ))}
    </div>
  );
}
