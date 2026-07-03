"use client";

/**
 * Correlation heatmap — a CSS-grid matrix of pairwise ρ between holdings.
 *
 * Semantics follow the diversification story, not "up=good": strongly
 * POSITIVE ρ (holdings move together → little diversification) shades toward
 * the destructive token; NEGATIVE ρ (natural hedges) toward primary; ~0 stays
 * neutral. Values are data from the backend (the engine's Pearson matrix) —
 * nothing is computed here beyond display.
 */

const MAX_DISPLAY = 14;

function cellBg(v: number | null): string | undefined {
  if (v == null) return undefined;
  const a = 0.05 + 0.55 * Math.min(1, Math.abs(v));
  if (v > 0) return `hsl(var(--destructive) / ${a.toFixed(2)})`;
  if (v < 0) return `hsl(var(--primary) / ${a.toFixed(2)})`;
  return undefined;
}

export function CorrHeatmap({
  tickers,
  matrix,
  totalTickers,
}: {
  tickers: string[];
  matrix: (number | null)[][];
  /** Full universe size when the payload/display is a top-N cut. */
  totalTickers?: number;
}) {
  const shown = tickers.slice(0, MAX_DISPLAY);
  const n = shown.length;
  if (n < 2) return null;
  const total = Math.max(totalTickers ?? tickers.length, tickers.length);

  return (
    <div className="space-y-1.5">
      <div className="overflow-x-auto">
        <div
          role="table"
          aria-label="Pairwise correlation of holdings"
          className="grid w-max gap-px font-mono text-[9px] tabular-nums"
          style={{ gridTemplateColumns: `2.6rem repeat(${n}, 2.4rem)` }}
        >
          <div />
          {shown.map((t) => (
            <div key={`h-${t}`} className="truncate px-0.5 py-1 text-center text-muted-foreground">
              {t}
            </div>
          ))}
          {shown.map((rowT, i) => (
            <RowCells key={rowT} rowT={rowT} i={i} shown={shown} matrix={matrix} />
          ))}
        </div>
      </div>
      <p className="text-[11px] text-muted-foreground">
        {total > n ? `Showing the top ${n} of ${total} holdings by portfolio weight. ` : ""}
        Red = moves together (adds concentration) · teal = moves opposite (a natural hedge).
      </p>
    </div>
  );
}

function RowCells({
  rowT,
  i,
  shown,
  matrix,
}: {
  rowT: string;
  i: number;
  shown: string[];
  matrix: (number | null)[][];
}) {
  return (
    <>
      <div className="truncate py-1 pr-1 text-right text-muted-foreground">{rowT}</div>
      {shown.map((colT, j) => {
        const v = matrix[i]?.[j] ?? null;
        const diag = i === j;
        return (
          <div
            key={`${rowT}-${colT}`}
            title={diag || v == null ? undefined : `${rowT} × ${colT} · ρ = ${v.toFixed(2)}`}
            className={`flex h-7 items-center justify-center rounded-sm ${
              diag ? "bg-muted text-muted-foreground/60" : "text-foreground/90"
            }`}
            style={diag ? undefined : { backgroundColor: cellBg(v) }}
          >
            {v == null ? "—" : diag ? "1.0" : v.toFixed(2)}
          </div>
        );
      })}
    </>
  );
}
