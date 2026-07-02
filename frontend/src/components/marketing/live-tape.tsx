"use client";

/**
 * Landing ticker tape — honest by construction.
 *
 * Feeds from the PUBLIC /api/v1/macro/movers endpoint (today's real top
 * gainers + losers, 10-min cached on both ends) and says so with a "Live ·
 * today's movers" label. Until data arrives — and whenever the endpoint is
 * empty/down (fail-soft) — it falls back to a fixed set of tickers that is
 * explicitly labelled "Illustrative", so the tape never *implies* live prices
 * it doesn't have. The static prerender ships the labelled illustrative tape
 * and hydrates to live data client-side.
 */

import { useMarketMovers, type MoverRow } from "@/lib/queries";
import { C, mono } from "@/components/marketing/theme";

type TapeItem = { ticker: string; price: string | null; changePct: number };

// Fixed fallback set (clearly labelled as illustrative in the UI) — shown
// during prerender/loading and whenever the movers endpoint has no rows.
const ILLUSTRATIVE: TapeItem[] = [
  ["NVDA", "172.41", 2.84], ["AAPL", "228.07", 0.62], ["MSFT", "461.20", 1.1],
  ["TSLA", "241.93", -3.17], ["SPY", "548.02", 0.41], ["TLT", "89.55", -0.41],
  ["AMZN", "201.30", 1.55], ["META", "612.88", 2.02], ["GOOGL", "178.44", -0.74],
  ["NFLX", "915.10", 0.93], ["AMD", "168.22", -1.21], ["BND", "72.19", 0.08],
].map(([t, p, d]) => ({ ticker: t as string, price: p as string, changePct: d as number }));

const MAX_ITEMS = 12;

function toTapeItems(rows: MoverRow[]): TapeItem[] {
  const seen = new Set<string>();
  const out: TapeItem[] = [];
  for (const r of rows) {
    if (r.change_pct == null || seen.has(r.ticker)) continue;
    seen.add(r.ticker);
    out.push({
      ticker: r.ticker,
      price: r.close != null ? r.close.toFixed(2) : null,
      changePct: r.change_pct,
    });
    if (out.length >= MAX_ITEMS) break;
  }
  return out;
}

export function LiveTape() {
  const movers = useMarketMovers();
  const live = toTapeItems([
    ...(movers.data?.top_gainers ?? []),
    ...(movers.data?.top_losers ?? []),
  ]);
  // Fewer than 4 real rows reads as a broken feed — use the labelled fallback.
  const isLive = live.length >= 4;
  const items = isLive ? live : ILLUSTRATIVE;
  const doubled = [...items, ...items];

  return (
    <div style={{ display: "flex", alignItems: "stretch", borderBlock: `1px solid ${C.hair}`, background: C.surfaceFaint }}>
      <span
        style={{
          display: "flex", alignItems: "center", gap: 7, padding: "0 14px",
          borderRight: `1px solid ${C.hair}`, whiteSpace: "nowrap", flexShrink: 0,
          ...mono, fontSize: 10.5, fontWeight: 600, textTransform: "uppercase", letterSpacing: ".12em", color: C.slate,
        }}
      >
        {isLive && <span aria-hidden style={{ width: 6, height: 6, borderRadius: "50%", background: C.up }} />}
        {isLive ? "Live · today's movers" : "Illustrative"}
      </span>
      <div style={{ overflow: "hidden", flex: 1, minWidth: 0 }}>
        <div style={{ display: "inline-flex", gap: 40, padding: "9px 0", whiteSpace: "nowrap", ...mono, fontSize: 12.5, animation: "mm-scroll 38s linear infinite" }}>
          {doubled.map((it, i) => (
            <span key={`${it.ticker}-${i}`} style={{ color: C.slate }}>
              <b style={{ color: C.paper, margin: "0 6px 0 8px" }}>{it.ticker}</b>
              {it.price != null && <>${it.price} </>}
              <span style={{ color: it.changePct >= 0 ? C.up : C.down }}>
                {it.changePct >= 0 ? "+" : ""}{it.changePct.toFixed(2)}%
              </span>
            </span>
          ))}
        </div>
        <style>{`@keyframes mm-scroll{to{transform:translateX(-50%)}}`}</style>
      </div>
    </div>
  );
}
