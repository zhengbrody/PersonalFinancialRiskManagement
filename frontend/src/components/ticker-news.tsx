"use client";

/**
 * Unified news rail for a ticker — FMP stock news + press releases + SEC
 * filings, each tagged with its type + provider source. Makes the multi-source
 * news layer visible (not a single Yahoo feed). Fail-soft: always shows at least
 * the SEC filings link.
 */

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { DataSourceBadges } from "@/components/data-source-badges";
import {
  useTickerNews,
  type UnifiedNewsItem,
  type TickerNews as TickerNewsData,
} from "@/lib/queries";

const TYPE_LABEL: Record<string, string> = {
  news: "News",
  press_release: "Press",
  earnings_transcript: "Transcript",
  filing: "Filing",
  macro: "Macro",
};

export function TickerNews({
  ticker,
  data,
}: {
  ticker: string | null;
  data?: TickerNewsData;
}) {
  const news = useTickerNews(data ? null : ticker);
  if (!ticker && !data) return null;
  const value = data ?? news.data;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-sm">News &amp; filings</CardTitle>
          {value && <DataSourceBadges sources={value.sources} />}
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {!data && news.isPending ? (
          <>
            <Skeleton className="h-8" />
            <Skeleton className="h-8" />
          </>
        ) : !data && news.isError ? (
          <p className="text-xs text-muted-foreground">Couldn&apos;t load news right now.</p>
        ) : (
          (value?.items ?? []).map((it, i) => <NewsRow key={i} item={it} />)
        )}
      </CardContent>
    </Card>
  );
}

function NewsRow({ item }: { item: UnifiedNewsItem }) {
  const body = (
    <div className="flex items-start gap-2">
      <span className="mt-0.5 rounded border border-border bg-muted/50 px-1 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
        {TYPE_LABEL[item.type] ?? item.type}
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-xs">{item.title}</p>
        <p className="text-[10px] text-muted-foreground">
          {item.source_label}
          {item.site && item.site !== item.source_label ? ` · ${item.site}` : ""}
          {item.published ? ` · ${item.published.slice(0, 10)}` : ""}
        </p>
      </div>
    </div>
  );
  return item.url ? (
    <a href={item.url} target="_blank" rel="noopener noreferrer" className="block hover:opacity-80">
      {body}
    </a>
  ) : (
    body
  );
}
