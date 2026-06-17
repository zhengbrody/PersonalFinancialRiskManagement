"use client";

/**
 * Export the current view as a professional, printable HTML report.
 *
 * Posts the data the page already has to /api/v1/reports/{kind}/html, gets back
 * a self-contained HTML document (server-rendered, deterministic, print-ready),
 * and opens it in a new tab where the user can read it or Save-as-PDF via the
 * browser's print dialog. No recompute, no credit. Analytics carries only the
 * report kind — never tickers / holdings / dollar values.
 */

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";
import { track } from "@/lib/analytics";
import { useAuth } from "@/lib/auth-context";
import { reportResponseSchema, type ReportResponse } from "@/lib/queries";

type ReportKind = "portfolio" | "ticker" | "options";

export function ReportExportButton({
  kind,
  payload,
  label = "Export report",
}: {
  kind: ReportKind;
  payload: Record<string, unknown> | null;
  label?: string;
}) {
  const { accessToken } = useAuth();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  if (!accessToken || !payload) return null;

  async function run() {
    if (busy) return;
    setBusy(true);
    setFailed(false);
    try {
      const res = await apiFetch<ReportResponse>(`/api/v1/reports/${kind}/html`, {
        method: "POST",
        body: payload,
        authToken: accessToken!,
        schema: reportResponseSchema,
      });
      const url = URL.createObjectURL(new Blob([res.html], { type: "text/html" }));
      window.open(url, "_blank", "noopener,noreferrer");
      // Safe: report kind only — no tickers / $ / holdings.
      track("report_export_clicked", { kind });
      // Give the new tab time to load before revoking the object URL.
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex items-center gap-2">
      <Button variant="outline" size="sm" onClick={run} disabled={busy}>
        {busy ? "Preparing…" : label}
      </Button>
      {failed && (
        <span className="text-xs text-muted-foreground">Couldn&apos;t build the report — try again.</span>
      )}
    </div>
  );
}
