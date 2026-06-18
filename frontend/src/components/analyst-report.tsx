"use client";

/**
 * Institutional analyst report (Phase 3). The backend assembles a self-contained
 * HTML document from the deterministic engines (no recomputation here); this
 * previews it in a sandboxed iframe and offers open/download (print → PDF).
 */

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useAnalystReport } from "@/lib/queries";

export function AnalystReportView({ ticker }: { ticker: string | null }) {
  const q = useAnalystReport(ticker);
  if (!ticker) return null;
  if (q.isLoading) {
    return (
      <Card>
        <CardContent className="space-y-3 py-6">
          <Skeleton className="h-5 w-48" />
          <Skeleton className="h-80 w-full" />
        </CardContent>
      </Card>
    );
  }
  if (q.isError || !q.data) {
    return (
      <Card>
        <CardContent className="py-6 text-sm text-muted-foreground">
          Couldn&apos;t build the report right now. It&apos;s assembled deterministically in the
          backend — please try again shortly.
        </CardContent>
      </Card>
    );
  }
  const r = q.data.report;

  function openOrDownload(download: boolean) {
    const blob = new Blob([r.html], { type: "text/html" });
    const url = URL.createObjectURL(blob);
    if (download) {
      const a = document.createElement("a");
      a.href = url;
      a.download = `${r.ticker}-research-report.html`;
      a.click();
    } else {
      window.open(url, "_blank", "noopener");
    }
    setTimeout(() => URL.revokeObjectURL(url), 4000);
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-base">{r.title}</CardTitle>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={() => openOrDownload(false)}>
              Open
            </Button>
            <Button size="sm" onClick={() => openOrDownload(true)}>
              Download HTML
            </Button>
          </div>
        </div>
        <CardDescription>
          Deterministic, source-attributed · {r.as_of ? `data as of ${r.as_of}` : "—"} · open or
          download, then print to PDF.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap gap-1.5">
          {r.sections
            .filter((s) => s.included)
            .map((s) => (
              <span
                key={s.key}
                className="rounded bg-muted px-2 py-0.5 text-[11px] text-muted-foreground"
              >
                {s.title}
              </span>
            ))}
        </div>
        <iframe
          title={`${r.ticker} research report`}
          srcDoc={r.html}
          sandbox=""
          className="h-[70vh] w-full rounded-md border border-border bg-white"
        />
      </CardContent>
    </Card>
  );
}
