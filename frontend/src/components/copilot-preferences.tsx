"use client";

/**
 * Copilot preferences — view, explicitly CONFIRM, update, and completely
 * clear. Nothing is ever saved without the user pressing Confirm (the PUT is
 * the confirmation act); preferences shape which risks the Copilot emphasises
 * and never override data confidence. Hidden entirely while the feature is
 * unavailable (503 = table not provisioned). No preference VALUES are sent to
 * analytics.
 */

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { track } from "@/lib/analytics";
import {
  type CopilotPreferences as Prefs,
  useClearCopilotPreferences,
  useCopilotPreferences,
  useSaveCopilotPreferences,
} from "@/lib/queries";

const HORIZONS = [
  { value: "", label: "Not set" },
  { value: "short", label: "Short (under ~2 years)" },
  { value: "medium", label: "Medium (~2–7 years)" },
  { value: "long", label: "Long (7+ years)" },
];
const LIQUIDITY = [
  { value: "", label: "Not set" },
  { value: "low", label: "Low — I rarely need to withdraw" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High — I may need cash soon" },
];

type FormState = {
  risk_tolerance: string;
  investment_horizon: string;
  liquidity_need: string;
  concentration_limit: string; // percent, "25" = 25%
  margin_limit: string;
};

function formFrom(p: Prefs | undefined): FormState {
  return {
    risk_tolerance: p?.risk_tolerance != null ? String(p.risk_tolerance) : "",
    investment_horizon: p?.investment_horizon ?? "",
    liquidity_need: p?.liquidity_need ?? "",
    concentration_limit:
      p?.concentration_limit != null ? String(Math.round(p.concentration_limit * 100)) : "",
    margin_limit: p?.margin_limit != null ? String(p.margin_limit) : "",
  };
}

export function CopilotPreferencesCard() {
  const prefs = useCopilotPreferences();
  const save = useSaveCopilotPreferences();
  const clear = useClearCopilotPreferences();
  const [form, setForm] = useState<FormState>(formFrom(undefined));
  const [confirmClear, setConfirmClear] = useState(false);

  useEffect(() => {
    if (prefs.data) setForm(formFrom(prefs.data));
  }, [prefs.data]);

  // Feature not provisioned / temporarily unavailable → hide entirely (same
  // contract as the weekly-digest card).
  if (prefs.isError) return null;

  const set = (k: keyof FormState) => (v: string) => setForm((f) => ({ ...f, [k]: v }));

  function submit(e: React.FormEvent) {
    e.preventDefault();
    // The Confirm button is disabled while saving, but pressing Enter in a
    // number input still fires onSubmit — guard so a save can't double-fire.
    if (save.isPending) return;
    const body = {
      risk_tolerance: form.risk_tolerance ? Number(form.risk_tolerance) : null,
      investment_horizon: form.investment_horizon || null,
      liquidity_need: form.liquidity_need || null,
      concentration_limit: form.concentration_limit
        ? Number(form.concentration_limit) / 100
        : null,
      margin_limit: form.margin_limit ? Number(form.margin_limit) : null,
    };
    save.mutate(body, {
      // Privacy: the event carries NO preference values.
      onSuccess: () => track("copilot_prefs_confirmed", {}),
    });
  }

  function doClear() {
    clear.mutate(undefined, {
      onSuccess: () => {
        setForm(formFrom(undefined));
        setConfirmClear(false);
        track("copilot_prefs_cleared", {});
      },
    });
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Copilot preferences (optional)</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-xs text-muted-foreground">
          Saved only when you press Confirm — never inferred from your chats or
          holdings. They tailor which risks the Copilot emphasises; they never
          change your data, scores or confidence gates.
        </p>

        {prefs.isLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-2/3" />
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-3">
            {prefs.data?.confirmed && (
              <p className="text-xs text-emerald-600 dark:text-emerald-400" role="status">
                Confirmed{prefs.data.confirmed_at ? ` · ${prefs.data.confirmed_at.slice(0, 10)}` : ""}
              </p>
            )}
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <label className="space-y-1 text-xs">
                <span className="font-medium">Risk tolerance (1 cautious – 5 aggressive)</span>
                <select
                  className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
                  value={form.risk_tolerance}
                  onChange={(e) => set("risk_tolerance")(e.target.value)}
                  aria-label="Risk tolerance"
                >
                  <option value="">Not set</option>
                  {[1, 2, 3, 4, 5].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
              <label className="space-y-1 text-xs">
                <span className="font-medium">Investment horizon</span>
                <select
                  className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
                  value={form.investment_horizon}
                  onChange={(e) => set("investment_horizon")(e.target.value)}
                  aria-label="Investment horizon"
                >
                  {HORIZONS.map((h) => (
                    <option key={h.value} value={h.value}>
                      {h.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="space-y-1 text-xs">
                <span className="font-medium">Liquidity need</span>
                <select
                  className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
                  value={form.liquidity_need}
                  onChange={(e) => set("liquidity_need")(e.target.value)}
                  aria-label="Liquidity need"
                >
                  {LIQUIDITY.map((h) => (
                    <option key={h.value} value={h.value}>
                      {h.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="space-y-1 text-xs">
                <span className="font-medium">Single-name limit (% of book)</span>
                <input
                  type="number"
                  min={0}
                  max={100}
                  step={1}
                  inputMode="numeric"
                  className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
                  value={form.concentration_limit}
                  onChange={(e) => set("concentration_limit")(e.target.value)}
                  aria-label="Single-name concentration limit percent"
                  placeholder="e.g. 25"
                />
              </label>
              <label className="space-y-1 text-xs">
                <span className="font-medium">Margin-leverage limit (×)</span>
                <input
                  type="number"
                  min={1}
                  max={10}
                  step={0.1}
                  inputMode="decimal"
                  className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
                  value={form.margin_limit}
                  onChange={(e) => set("margin_limit")(e.target.value)}
                  aria-label="Margin leverage limit"
                  placeholder="e.g. 1.5"
                />
              </label>
            </div>

            {save.isError && (
              <p className="text-xs text-destructive" role="alert">
                Could not save — check the values and try again.
              </p>
            )}

            <div className="flex flex-wrap items-center gap-2">
              <Button type="submit" size="sm" disabled={save.isPending}>
                {save.isPending ? "Saving…" : "Confirm preferences"}
              </Button>
              {prefs.data?.confirmed &&
                (confirmClear ? (
                  <>
                    <Button
                      type="button"
                      size="sm"
                      variant="destructive"
                      onClick={doClear}
                      disabled={clear.isPending}
                    >
                      {clear.isPending ? "Clearing…" : "Yes, erase completely"}
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => setConfirmClear(false)}
                    >
                      Keep them
                    </Button>
                  </>
                ) : (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => setConfirmClear(true)}
                  >
                    Clear all preferences
                  </Button>
                ))}
            </div>
          </form>
        )}
      </CardContent>
    </Card>
  );
}
