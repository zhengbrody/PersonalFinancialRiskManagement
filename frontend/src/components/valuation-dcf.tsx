"use client";

/**
 * Deterministic DCF valuation (Phase 2). Every number comes from the backend
 * engine; this component only edits assumptions and renders results. The editor
 * posts overrides and the backend recomputes — the UI never does valuation math.
 * Educational only; not investment advice.
 */

import { useEffect, useState } from "react";
import {
  Bar,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useDcf, type DcfOutput } from "@/lib/queries";

const pct = (v: number | null | undefined, d = 1) =>
  v == null || !Number.isFinite(v) ? "—" : `${(v * 100).toFixed(d)}%`;
const usd = (v: number | null | undefined) => {
  if (v == null || !Number.isFinite(v)) return "—";
  const a = Math.abs(v);
  if (a >= 1e12) return `$${(v / 1e12).toFixed(2)}T`;
  if (a >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (a >= 1e6) return `$${(v / 1e6).toFixed(0)}M`;
  return `$${v.toFixed(2)}`;
};

const SRC_TONE: Record<string, string> = {
  reported: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  derived: "bg-sky-500/15 text-sky-700 dark:text-sky-300",
  default: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  user_override: "bg-primary/15 text-primary",
  unavailable: "bg-red-500/15 text-red-700 dark:text-red-300",
};

type Editor = {
  wacc: string;
  terminal_growth: string;
  tax_rate: string;
  revenue_growth: string;
  operating_margin: string;
  projection_years: string;
};

export function ValuationDcf({
  ticker,
  data,
}: {
  ticker: string | null;
  data?: DcfOutput;
}) {
  const dcf = useDcf();
  const { mutate } = dcf;
  const [edit, setEdit] = useState<Editor | null>(null);

  // Fetch the base DCF on ticker change — unless `data` (the consolidated
  // bundle's base DCF) was supplied, in which case we render it directly and
  // only call the backend when the user edits + recalculates.
  useEffect(() => {
    if (ticker && !data) mutate({ ticker });
    setEdit(null);
  }, [ticker, data, mutate]);

  // Seed the editor once from the derived base assumptions. A recalc result
  // (dcf.data) wins over the bundle's base.
  const out = dcf.data?.dcf ?? data;
  useEffect(() => {
    if (out && edit === null) {
      const i = out.inputs;
      const g0 = i.revenue_growth[0]?.value ?? 0.05;
      const m0 = i.operating_margin[0]?.value ?? 0.2;
      setEdit({
        wacc: ((i.wacc.value ?? 0.09) * 100).toFixed(1),
        terminal_growth: ((i.terminal_growth.value ?? 0.025) * 100).toFixed(1),
        tax_rate: ((i.tax_rate.value ?? 0.21) * 100).toFixed(1),
        revenue_growth: (g0 * 100).toFixed(1),
        operating_margin: (m0 * 100).toFixed(1),
        projection_years: String(i.projection_years),
      });
    }
  }, [out, edit]);

  if (!ticker) return null;
  if (dcf.isPending && !out) return <DcfSkeleton />;
  if (dcf.isError && !out) {
    return (
      <Card>
        <CardContent className="py-6 text-sm text-muted-foreground">
          Couldn&apos;t build the DCF right now. The figures are computed in the backend — try again
          in a moment.
        </CardContent>
      </Card>
    );
  }
  if (!out || !edit) return <DcfSkeleton />;

  function recalc() {
    if (!ticker || !edit) return;
    const num = (s: string) => {
      const n = Number(s);
      return Number.isFinite(n) ? n : undefined;
    };
    mutate({
      ticker,
      overrides: {
        wacc: num(edit.wacc) != null ? num(edit.wacc)! / 100 : undefined,
        terminal_growth:
          num(edit.terminal_growth) != null ? num(edit.terminal_growth)! / 100 : undefined,
        tax_rate: num(edit.tax_rate) != null ? num(edit.tax_rate)! / 100 : undefined,
        revenue_growth:
          num(edit.revenue_growth) != null ? [num(edit.revenue_growth)! / 100] : undefined,
        operating_margin:
          num(edit.operating_margin) != null ? num(edit.operating_margin)! / 100 : undefined,
        projection_years: num(edit.projection_years),
      },
    });
  }

  return (
    <div className="space-y-4">
      <ScenarioRange out={out} />
      <AssumptionEditor out={out} edit={edit} setEdit={setEdit} onApply={recalc} pending={dcf.isPending} />
      {out.valid ? (
        <>
          <ProjectionChart out={out} />
          {out.sensitivity.map((s, i) => (
            <SensitivityTable key={i} s={s} />
          ))}
        </>
      ) : (
        <Card>
          <CardContent className="space-y-1 py-4 text-sm">
            <p className="font-medium text-amber-700 dark:text-amber-300">DCF not valid with these inputs</p>
            {out.warnings.map((w) => (
              <p key={w} className="text-muted-foreground">
                {w}
              </p>
            ))}
          </CardContent>
        </Card>
      )}
      <p className="text-[11px] leading-relaxed text-muted-foreground">{out.disclaimer}</p>
    </div>
  );
}

function ScenarioRange({ out }: { out: DcfOutput }) {
  const by = Object.fromEntries(out.scenarios.map((s) => [s.name, s.implied_value_per_share]));
  const price = out.current_price;
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Implied value vs price</CardTitle>
        <CardDescription>
          Deterministic bear / base / bull per-share value{out.as_of ? ` · as of ${out.as_of}` : ""}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Current price" value={usd(price)} />
          <Stat label="Bear" value={usd(by.bear as number)} />
          <Stat label="Base" value={usd(by.base as number)} accent />
          <Stat label="Bull" value={usd(by.bull as number)} />
        </div>
        {out.upside_pct != null && (
          <p className="text-sm">
            Base case implies{" "}
            <span className={out.upside_pct >= 0 ? "font-semibold text-emerald-600" : "font-semibold text-red-600"}>
              {pct(out.upside_pct)} {out.upside_pct >= 0 ? "upside" : "downside"}
            </span>{" "}
            vs the current price.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function AssumptionEditor({
  out,
  edit,
  setEdit,
  onApply,
  pending,
}: {
  out: DcfOutput;
  edit: Editor;
  setEdit: (e: Editor) => void;
  onApply: () => void;
  pending: boolean;
}) {
  const i = out.inputs;
  const field = (key: keyof Editor, label: string, src: { source_type: string }) => (
    <label className="space-y-1 text-sm">
      <span className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-muted-foreground">
        {label}
        <span className={`rounded px-1 py-px text-[9px] font-medium ${SRC_TONE[src.source_type] ?? ""}`}>
          {src.source_type.replace("_", " ")}
        </span>
      </span>
      <input
        type="number"
        step="0.1"
        value={edit[key]}
        onChange={(e) => setEdit({ ...edit, [key]: e.target.value })}
        className="w-full rounded-md border border-border bg-background px-2 py-1 tabular-nums"
      />
    </label>
  );
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Assumptions</CardTitle>
        <CardDescription>Edit and recalculate — every value is labeled by source.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {field("revenue_growth", "Rev growth %", i.revenue_growth[0] ?? { source_type: "derived" })}
          {field("operating_margin", "Op margin %", i.operating_margin[0] ?? { source_type: "reported" })}
          {field("tax_rate", "Tax %", i.tax_rate)}
          {field("wacc", "WACC %", i.wacc)}
          {field("terminal_growth", "Term growth %", i.terminal_growth)}
          {field("projection_years", "Years", { source_type: "default" })}
        </div>
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground">
            Net debt {usd(i.net_debt.value)} · {usd(i.diluted_shares.value)} dil. shares
          </span>
          <Button size="sm" onClick={onApply} disabled={pending}>
            {pending ? "Recalculating…" : "Recalculate"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function ProjectionChart({ out }: { out: DcfOutput }) {
  const data = out.projections.map((p) => ({
    year: `Y${p.year}`,
    Revenue: Math.round(p.revenue / 1e9),
    FCF: Math.round(p.fcf / 1e9),
  }));
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Projected revenue &amp; free cash flow ($B)</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-56 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -8 }}>
              <XAxis dataKey="year" tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} />
              <YAxis tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} />
              <Tooltip
                contentStyle={{
                  background: "hsl(var(--card))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: 8,
                  fontSize: 12,
                }}
              />
              <Bar dataKey="Revenue" fill="hsl(var(--primary))" radius={[3, 3, 0, 0]} opacity={0.85} />
              <Line dataKey="FCF" stroke="#D4A017" strokeWidth={2} dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}

function SensitivityTable({ s }: { s: DcfOutput["sensitivity"][number] }) {
  const all = s.values.flat().filter((v): v is number => v != null);
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  const tone = (v: number | null) => {
    if (v == null || hi === lo) return "";
    const f = (v - lo) / (hi - lo);
    return f > 0.66 ? "text-emerald-600" : f < 0.33 ? "text-red-600" : "";
  };
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">{s.title}</CardTitle>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <table className="w-full min-w-[460px] text-right text-xs tabular-nums">
          <thead>
            <tr className="text-[10px] uppercase tracking-wide text-muted-foreground">
              <th className="py-1 text-left">
                {s.row_label} ↓ / {s.col_label} →
              </th>
              {s.cols.map((c) => (
                <th key={c} className="font-medium">
                  {(c * 100).toFixed(1)}%
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {s.rows.map((r, i) => (
              <tr key={r} className="border-t border-border/40">
                <td className="py-1 text-left font-medium">{(r * 100).toFixed(1)}%</td>
                {s.values[i].map((v, j) => (
                  <td key={j} className={tone(v)}>
                    {v == null ? "—" : usd(v)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={`font-mono font-semibold ${accent ? "text-primary" : ""}`}>{value}</p>
    </div>
  );
}

function DcfSkeleton() {
  return (
    <Card>
      <CardContent className="space-y-3 py-6">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-40 w-full" />
      </CardContent>
    </Card>
  );
}
