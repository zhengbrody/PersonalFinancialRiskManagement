"use client";

import Link from "next/link";
import { useAuth } from "@/lib/auth-context";

/**
 * Top-level page shell with sticky header + max-w container.
 * Header renders the auth pill on the right: signed-in users see
 * `email · Sign out`, anon users see `Sign in`. The pill is hidden
 * during the initial Supabase session load to avoid a flicker.
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
            <Link
              href="/markets"
              className="rounded px-3 py-1.5 text-muted-foreground hover:bg-accent hover:text-accent-foreground"
            >
              Markets
            </Link>
            <Link
              href="/portfolios"
              className="rounded px-3 py-1.5 text-muted-foreground hover:bg-accent hover:text-accent-foreground"
            >
              Portfolios
            </Link>
            <Link
              href="/pricing"
              className="rounded px-3 py-1.5 text-muted-foreground hover:bg-accent hover:text-accent-foreground"
            >
              Pricing
            </Link>
            <a
              href="/legacy/"
              className="rounded px-3 py-1.5 text-muted-foreground hover:bg-accent hover:text-accent-foreground"
            >
              Legacy
            </a>
            <AuthPill />
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-10">{children}</main>
    </div>
  );
}

function AuthPill() {
  const { user, loading, configured, signOut } = useAuth();

  if (loading) {
    return <span className="ml-2 h-5 w-16 animate-pulse rounded bg-muted" />;
  }
  if (!configured) {
    // Supabase env not set. Hide the pill rather than offer a broken
    // sign-in link — the /score public flow still works.
    return null;
  }
  if (!user) {
    return (
      <div className="ml-2 flex items-center gap-1">
        <Link
          href="/login"
          className="rounded-md px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent hover:text-accent-foreground"
        >
          Sign in
        </Link>
        <Link
          href="/signup"
          className="rounded-md border border-primary/50 bg-primary/10 px-3 py-1.5 text-sm text-primary hover:bg-primary/20"
        >
          Sign up
        </Link>
      </div>
    );
  }
  return (
    <div className="ml-2 flex items-center gap-2">
      <Link
        href="/settings"
        className="hidden font-mono text-xs text-muted-foreground hover:text-foreground sm:inline"
        title={user.email ?? user.id}
      >
        {user.email ?? user.id}
      </Link>
      <button
        type="button"
        onClick={() => signOut()}
        className="rounded-md border border-border bg-transparent px-3 py-1.5 text-sm hover:bg-accent hover:text-accent-foreground"
      >
        Sign out
      </button>
    </div>
  );
}
