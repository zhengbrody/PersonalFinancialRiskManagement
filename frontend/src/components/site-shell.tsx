"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { isBillingEnabled } from "@/lib/billing-flag";
import { useAuth } from "@/lib/auth-context";
import { displayName } from "@/lib/user-display";
import { useBillingMe } from "@/lib/queries";
import { FloatingCopilot } from "@/components/floating-copilot";
import { FeedbackWidget } from "@/components/feedback-widget";
import { MarketStatusBar } from "@/components/market-status-bar";
import { Logo } from "@/components/ui/logo";
import { Badge } from "@/components/ui/badge";

/**
 * Top-level page shell with sticky header + max-w container.
 *
 * The nav is grouped by the user's JOURNEY (own → research → ask AI) rather
 * than a flat list, so it tells the product story and scales as features land:
 *   Portfolio ▾   Research ▾   Copilot          [plan] Account ▾
 * Power features sit one click deep; the AI Copilot stays top-level (it's the
 * differentiator). The right-side Account menu folds in plan, billing, the
 * owner admin, and sign-out.
 */

type NavItem = { href: string; label: string; external?: boolean };

const PORTFOLIO_ITEMS: NavItem[] = [
  { href: "/score", label: "Health Score" },
  { href: "/portfolios", label: "Holdings" },
  { href: "/risk", label: "Risk" },
  { href: "/quant", label: "Backtest" },
  { href: "/scenarios", label: "Scenarios" },
];

const RESEARCH_ITEMS: NavItem[] = [
  { href: "/research", label: "Stocks" },
  { href: "/markets", label: "Markets" },
  { href: "/institutions", label: "Smart money" },
];

/** Account-menu links, shared by the desktop AccountMenu + the mobile menu. */
function accountLinks(isOwner: boolean): NavItem[] {
  return [
    { href: "/settings", label: "Settings" },
    // Pricing / billing is hidden during the free beta (Stripe stays in code).
    ...(isBillingEnabled()
      ? [{ href: "/pricing", label: "Plan & billing" } as NavItem]
      : []),
    ...(isOwner ? [{ href: "/admin", label: "Admin · usage" } as NavItem] : []),
  ];
}

/**
 * Pre-login marketing/content + auth routes are full-bleed: they wear the
 * premium <MarketingShell/> (its own fixed nav + footer), NOT the app header.
 * "/" and "/markets" are AUTH-CONDITIONAL — anonymous → full-bleed marketing
 * (the landing / the markets intro), signed-in → the normal app shell.
 */
const FULL_BLEED_ROUTES = new Set([
  "/product",
  "/learn",
  "/demo-risk-check",
  "/risk-today",
  "/resources",
  "/login",
  "/signup",
  "/legal",
]);
const ANON_FULL_BLEED_ROUTES = new Set(["/", "/markets"]);

export function SiteShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user, configured } = useAuth();
  const isAnonFullBleed = ANON_FULL_BLEED_ROUTES.has(pathname) && !(configured && user);
  if (
    isAnonFullBleed ||
    FULL_BLEED_ROUTES.has(pathname) ||
    pathname.startsWith("/learn/") ||
    pathname.startsWith("/legal/")
  ) {
    return <>{children}</>;
  }
  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-40 border-b border-border bg-background/80 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
          <Link
            href="/"
            className="flex items-center gap-2 text-sm font-semibold tracking-tight"
          >
            <Logo size={20} />
            MindMarket
            <Badge tone="neutral" uppercase>
              Beta
            </Badge>
          </Link>
          {/* Desktop nav */}
          <nav className="hidden items-center gap-1 text-sm md:flex">
            <NavGroup label="Portfolio" items={PORTFOLIO_ITEMS} />
            <NavGroup label="Research" items={RESEARCH_ITEMS} />
            <Link
              href="/copilot"
              className="rounded px-3 py-1.5 font-medium text-foreground hover:bg-accent hover:text-accent-foreground"
            >
              Copilot
            </Link>
            <AccountMenu />
          </nav>
          {/* Mobile nav */}
          <MobileNav />
        </div>
        <MarketStatusBar />
      </header>
      <main className="mx-auto max-w-6xl px-4 py-10">{children}</main>
      <FloatingCopilot />
      <FeedbackWidget />
    </div>
  );
}

/** Close `open` when clicking outside `ref` or pressing Escape. The latest
 * `close` is read via a ref so the listeners subscribe once per open/close
 * (not on every re-render while open). */
function useDismiss(open: boolean, close: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(close);
  closeRef.current = close;
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) closeRef.current();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeRef.current();
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  return ref;
}

function NavGroup({ label, items }: { label: string; items: NavItem[] }) {
  const [open, setOpen] = useState(false);
  const ref = useDismiss(open, () => setOpen(false));
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="menu"
        className="flex items-center gap-1 rounded px-3 py-1.5 text-muted-foreground hover:bg-accent hover:text-accent-foreground"
      >
        {label}
        <span aria-hidden className="text-[10px] opacity-70">
          ▾
        </span>
      </button>
      {open && (
        <div
          role="menu"
          className="absolute left-0 z-50 mt-1 min-w-44 rounded-md border border-border bg-card p-1 shadow-lg"
        >
          {items.map((it) => (
            <MenuLink key={it.href} item={it} onNavigate={() => setOpen(false)} />
          ))}
        </div>
      )}
    </div>
  );
}

function MenuLink({ item, onNavigate }: { item: NavItem; onNavigate: () => void }) {
  const cls =
    "block rounded px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent hover:text-accent-foreground";
  if (item.external) {
    return (
      <a href={item.href} role="menuitem" className={cls} onClick={onNavigate}>
        {item.label}
      </a>
    );
  }
  return (
    <Link href={item.href} role="menuitem" className={cls} onClick={onNavigate}>
      {item.label}
    </Link>
  );
}

function MobileNav() {
  const { user, configured, signOut } = useAuth();
  const billing = useBillingMe();
  const [open, setOpen] = useState(false);
  const ref = useDismiss(open, () => setOpen(false));
  const close = () => setOpen(false);
  const isOwner = billing.data?.plan === "owner";

  return (
    <div ref={ref} className="relative md:hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label="Menu"
        className="flex h-9 w-9 items-center justify-center rounded-md border border-border text-foreground hover:bg-accent"
      >
        <span aria-hidden className="text-lg leading-none">
          {open ? "✕" : "☰"}
        </span>
      </button>
      {open && (
        <div className="absolute right-0 z-50 mt-2 w-60 rounded-md border border-border bg-card p-2 shadow-lg">
          <Section label="Portfolio" items={PORTFOLIO_ITEMS} onNavigate={close} />
          <Section label="Research" items={RESEARCH_ITEMS} onNavigate={close} />
          <MenuLink item={{ href: "/copilot", label: "Copilot" }} onNavigate={close} />
          <div className="my-1 border-t border-border" />
          {configured && user ? (
            <>
              {accountLinks(isOwner).map((it) => (
                <MenuLink key={it.href} item={it} onNavigate={close} />
              ))}
              <button
                type="button"
                onClick={() => {
                  close();
                  signOut();
                }}
                className="block w-full rounded px-3 py-1.5 text-left text-sm text-muted-foreground hover:bg-accent hover:text-accent-foreground"
              >
                Sign out
              </button>
            </>
          ) : configured ? (
            <>
              <MenuLink item={{ href: "/login", label: "Sign in" }} onNavigate={close} />
              <MenuLink item={{ href: "/signup", label: "Sign up" }} onNavigate={close} />
            </>
          ) : null}
        </div>
      )}
    </div>
  );
}

function Section({
  label,
  items,
  onNavigate,
}: {
  label: string;
  items: NavItem[];
  onNavigate: () => void;
}) {
  return (
    <div className="mb-1">
      <div className="px-3 pb-0.5 pt-1 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
        {label}
      </div>
      {items.map((it) => (
        <MenuLink key={it.href} item={it} onNavigate={onNavigate} />
      ))}
    </div>
  );
}

function AccountMenu() {
  const { user, loading, configured, signOut } = useAuth();
  const billing = useBillingMe();
  const [open, setOpen] = useState(false);
  const ref = useDismiss(open, () => setOpen(false));

  if (loading) {
    return <span className="ml-2 h-5 w-16 animate-pulse rounded bg-muted" />;
  }
  // Supabase env not set → hide rather than offer a broken sign-in link.
  if (!configured) return null;

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

  const plan = billing.data?.plan;
  const isOwner = plan === "owner";

  return (
    <div ref={ref} className="relative ml-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="menu"
        title={displayName(user)}
        className="flex items-center gap-2 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent hover:text-accent-foreground"
      >
        {isBillingEnabled() && plan && (
          <Badge tone="primary" uppercase>
            {plan}
          </Badge>
        )}
        <span className="hidden max-w-[14ch] truncate text-xs text-muted-foreground sm:inline">
          {displayName(user)}
        </span>
        <span aria-hidden className="text-[10px] opacity-70">
          ▾
        </span>
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 z-50 mt-1 min-w-48 rounded-md border border-border bg-card p-1 shadow-lg"
        >
          {accountLinks(isOwner).map((it) => (
            <MenuLink key={it.href} item={it} onNavigate={() => setOpen(false)} />
          ))}
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              signOut();
            }}
            className="block w-full rounded px-3 py-1.5 text-left text-sm text-muted-foreground hover:bg-accent hover:text-accent-foreground"
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
