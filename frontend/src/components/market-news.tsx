"use client";

/**
 * Macro news list (public, fail-soft). Shows source-labeled headlines from the
 * macro news service so the user can see the publisher mix, not just a generic
 * "Yahoo" feed. Renders an empty note rather than erroring if the feed is down.
 */

import { DataSourceBadges } from "@/components/data-source-badges";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useMarketNews, type NewsItem } from "@/lib/queries";

export function MarketNews() {
  const q = useMarketNews();
  const items = (q.data?.items ?? []) as NewsItem[];

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Market news</CardTitle>
        <CardDescription>The macro headlines moving markets right now.</CardDescription>
        {q.data?.sources && <DataSourceBadges sources={q.data.sources} />}
      </CardHeader>
      <CardContent className="space-y-2">
        {q.isLoading && (
          <>
            <Skeleton className="h-10" />
            <Skeleton className="h-10" />
            <Skeleton className="h-10" />
          </>
        )}
        {!q.isLoading && items.length === 0 && (
          <p className="text-sm text-muted-foreground">News feed is quiet right now.</p>
        )}
        {items.slice(0, 12).map((n, i) => (
          <a
            key={i}
            href={n.link ?? "#"}
            target="_blank"
            rel="noopener noreferrer"
            className="block rounded-md border border-border px-3 py-2 transition hover:bg-accent"
          >
            <div className="text-sm font-medium leading-snug">{n.title}</div>
            <div className="mt-0.5 text-xs text-muted-foreground">
              {[n.source, n.published].filter(Boolean).join(" · ")}
            </div>
          </a>
        ))}
      </CardContent>
    </Card>
  );
}
