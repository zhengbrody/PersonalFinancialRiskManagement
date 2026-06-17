"use client";

/**
 * Owner "API balance" card — remaining LLM credit so the owner knows when to top
 * up. DeepSeek shows its LIVE API balance; Claude shows an ESTIMATE (the top-up
 * you set − tracked Claude spend, since Anthropic exposes no balance API). Amber
 * (and a header banner) when any provider is low. Pure display of /admin/balances.
 */

import { useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { useSetAnthropicTopup, type AdminBalances, type BalanceProvider } from "@/lib/queries";

const BALANCE_TEXT: Record<string, string> = {
  ok: "text-emerald-600 dark:text-emerald-400",
  warn: "text-amber-600 dark:text-amber-400",
  critical: "text-red-600 dark:text-red-400",
  unknown: "text-muted-foreground",
};
const BALANCE_BAR: Record<string, string> = {
  ok: "bg-emerald-500",
  warn: "bg-amber-500",
  critical: "bg-red-500",
  unknown: "bg-muted-foreground/40",
};

export function ApiBalanceCard({ data, loading }: { data?: AdminBalances; loading: boolean }) {
  if (loading && !data) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">API balance</CardTitle>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-20 w-full" />
        </CardContent>
      </Card>
    );
  }
  if (!data) return null;
  const providers = [data.deepseek, data.anthropic].filter(Boolean) as BalanceProvider[];
  const anyLow = providers.some((p) => p.low);
  return (
    <Card className={anyLow ? "border-amber-500/40" : undefined}>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center justify-between text-base">
          <span>API balance</span>
          {anyLow && (
            <span className="text-xs font-medium text-amber-600 dark:text-amber-400">
              ⚠ 低余量 · 该充值
            </span>
          )}
        </CardTitle>
        <CardDescription>
          每 45 秒刷新 · DeepSeek 实时余额,Claude 为估算(你的充值额 − 已用)
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 sm:grid-cols-2">
        {providers.map((p) => (
          <ProviderBalance key={p.provider} p={p} />
        ))}
      </CardContent>
    </Card>
  );
}

function ProviderBalance({ p }: { p: BalanceProvider }) {
  const tone = BALANCE_TEXT[p.status] ?? "text-muted-foreground";
  const money = (n?: number | null) => {
    if (typeof n !== "number") return "—";
    const foreign = p.currency && p.currency !== "USD";
    return foreign ? `${n.toFixed(2)} ${p.currency}` : `$${n.toFixed(2)}`;
  };
  const topped = typeof p.topped_up === "number" ? p.topped_up : 0;
  const remaining = typeof p.remaining === "number" ? p.remaining : 0;
  return (
    <div className="rounded-lg border border-border bg-background/40 p-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">{p.provider}</span>
        <span className="rounded-full border border-border px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
          {p.source === "live" ? "live" : "estimate"}
        </span>
      </div>
      {!p.configured ? (
        <p className="mt-2 text-xs text-muted-foreground">
          {p.provider.startsWith("Claude")
            ? "未配置 — 在 EC2 .env 设 ANTHROPIC_TOPUP_USD(你充值的 Claude 额度)"
            : "未配置 — 缺 DEEPSEEK_API_KEY"}
        </p>
      ) : p.error ? (
        <p className="mt-2 text-xs text-amber-600 dark:text-amber-400">暂时取不到余额({p.error})</p>
      ) : (
        <>
          <p className={cn("mt-1 font-mono text-2xl font-semibold tabular-nums", tone)}>
            {money(p.remaining)}
          </p>
          <p className="text-xs text-muted-foreground">
            {p.source === "estimate"
              ? `充 ${money(p.topped_up)} · 已用 ${money(p.spent)}`
              : topped > 0
                ? `含充值 ${money(p.topped_up)}`
                : "可用余额"}
          </p>
          {topped > 0 && (
            <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-muted">
              <div
                className={cn("h-full rounded-full", BALANCE_BAR[p.status] ?? "bg-muted-foreground/40")}
                style={{ width: `${Math.max(0, Math.min(100, (remaining / topped) * 100))}%` }}
              />
            </div>
          )}
          {p.low && <p className={cn("mt-1.5 text-xs font-medium", tone)}>⚠ 余量偏低 — 建议充值</p>}
        </>
      )}
      {/* Claude has no balance API → owner enters the new balance after a top-up
          (no env edit / restart); spend then counts down from here live. */}
      {p.source === "estimate" && <ClaudeTopupEditor />}
    </div>
  );
}

function ClaudeTopupEditor() {
  const [open, setOpen] = useState(false);
  const [val, setVal] = useState("");
  const mut = useSetAnthropicTopup();

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="mt-2 text-xs text-primary hover:underline"
      >
        ✎ 充值后更新余额
      </button>
    );
  }
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        const n = parseFloat(val);
        if (!Number.isNaN(n) && n >= 0) {
          mut.mutate(n, { onSuccess: () => setOpen(false) });
        }
      }}
      className="mt-2 flex flex-wrap items-center gap-1.5"
    >
      <input
        type="number"
        step="0.01"
        min="0"
        value={val}
        onChange={(e) => setVal(e.target.value)}
        placeholder="新余额 $"
        autoFocus
        className="w-28 rounded border border-border bg-background px-2 py-1 text-sm tabular-nums"
      />
      <button
        type="submit"
        disabled={mut.isPending}
        className="rounded bg-primary px-2 py-1 text-xs font-medium text-primary-foreground disabled:opacity-50"
      >
        {mut.isPending ? "…" : "保存"}
      </button>
      <button
        type="button"
        onClick={() => setOpen(false)}
        className="text-xs text-muted-foreground hover:underline"
      >
        取消
      </button>
      {mut.isError && <span className="text-xs text-red-600 dark:text-red-400">保存失败</span>}
    </form>
  );
}
