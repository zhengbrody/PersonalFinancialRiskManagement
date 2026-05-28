import Link from "next/link";

/**
 * Top-level page shell.
 * Sticky header + max-w container. Lives outside the layout so we can
 * tweak the chrome without re-templating every page.
 */
export function SiteShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-40 border-b border-border bg-background/80 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
          <Link
            href="/"
            className="flex items-center gap-2 text-sm font-semibold tracking-tight"
          >
            <span className="inline-block h-2 w-2 rounded-full bg-primary" />
            MindMarket
            <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium uppercase text-muted-foreground">
              alpha
            </span>
          </Link>
          <nav className="flex items-center gap-1 text-sm">
            <Link
              href="/score"
              className="rounded px-3 py-1.5 text-muted-foreground hover:bg-accent hover:text-accent-foreground"
            >
              Score
            </Link>
            <a
              href="http://localhost:8000/docs"
              target="_blank"
              rel="noreferrer"
              className="rounded px-3 py-1.5 text-muted-foreground hover:bg-accent hover:text-accent-foreground"
            >
              API
            </a>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-10">{children}</main>
    </div>
  );
}
