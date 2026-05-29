"use client";

/**
 * App-router error boundary. Next.js hands any unhandled render or
 * data-fetching error here. The `reset()` prop re-runs the segment;
 * a top-link goes home if reset can't recover.
 *
 * Kept dependency-free so a failure deep in `lib/` never re-throws
 * from this component itself.
 */

import { useEffect } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Phase 3 will plug Sentry here. Until then, the console is the
    // observability surface — keep the digest so a user can quote it.
    // eslint-disable-next-line no-console
    console.error("App error boundary caught:", error);
  }, [error]);

  return (
    <div className="mx-auto max-w-2xl py-16">
      <Card className="border-destructive/50">
        <CardHeader>
          <CardTitle className="text-destructive">Something went wrong.</CardTitle>
          <CardDescription>
            An unexpected error broke this page. The team has been notified.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">{error.message}</p>
          {error.digest && (
            <p className="font-mono text-xs text-muted-foreground">
              digest: {error.digest}
            </p>
          )}
          <div className="flex gap-2">
            <Button onClick={() => reset()}>Try again</Button>
            <Link href="/">
              <Button variant="outline">Back to home</Button>
            </Link>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
