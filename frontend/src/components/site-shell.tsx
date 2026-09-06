"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { isBillingEnabled } from "@/lib/billing-flag";
import { useAuth } from "@/lib/auth-context";
import { displayName } from "@/lib/user-display";
import { useBillingMe } from "@/lib/queries";
import { FloatingCopilot } from "@/components/floating-copilot";
import { FeedbackWidget } from "@/components/feedback-widget";
import { MarketStatusBar } from "@/components/market-status-bar";
import { PortfolioContextBar } from "@/components/portfolio-context-bar";
import { useDismiss } from "@/lib/use-dismiss";
import { Logo } from "@/components/ui/logo";
import { Badge } from "@/components/ui/badge";
import { WorkspaceIcon } from "@/components/ui/workspace-icon";
import { isWorkspaceRoute, WORKSPACE_LINKS } from "@/lib/workspace-navigation";

/**
 * Shared signed-in workspace shell. Primary destinations use one navigation
 * model across the desktop header and compact-screen bottom bar. Research's
 * related surfaces and account utilities remain one level deep.
 */

type NavItem = { href: string; label: string; external?: boolean };

const MAIN_LINKS = WORKSPACE_LINKS.filter(
  (item) => item.href !== "/research" && item.href !== "/copilot",
);

const RESEARCH_ITEMS: NavItem[] = [
  { href: "/research", label: "Stocks" },
  { href: "/markets", label: "Markets" },
  { href: "/institutions", label: "Smart money" },
];

/** Secondary account actions. Holdings is a first-class workspace destination. */
function accountLinks(isOwner: boolean): NavItem[] {
  return [
    { href: "/quant", label: "Backtest" },
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
  // Migrated SEO landing pages (formerly Caddy-served assets/seo/*.html) — they
  // wear MarketingShell themselves, so keep the app header off.
  "/about",
  "/portfolio-risk-management",
  "/ai-portfolio-analysis",
  "/portfolio-var-stress-testing",
  "/personal-portfolio-risk-analysis",
  "/margin-risk-calculator",
  "/portfolio-stress-test",
  "/stock-portfolio-concentration-risk",
  "/robinhood-margin-risk",
  "/sample-risk-report",
]);
const ANON_FULL_BLEED_ROUTES = new Set(["/", "/markets"]);

export function SiteShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user, configured } = useAuth();
  const isAnonFullBleed =
    ANON_FULL_BLEED_ROUTES.has(pathname) && !(configured && user);
  if (
    isAnonFullBleed ||
    FULL_BLEED_ROUTES.has(pathname) ||
    pathname.startsWith("/learn/") ||
    pathname.startsWith("/legal/") ||
    pathname.startsWith("/methodology/")
  ) {
    return <>{children}</>;
  }
  return (
    <div className="workspace-shell min-h-screen bg-background text-foreground">
      <a
        href="#workspace-content"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[100] focus:rounded-lg focus:bg-card focus:p-3"
      >
        Skip to workspace
      </a>
      <header className="sticky top-0 z-40 border-b border-border bg-background/95 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-[1400px] items-center justify-between gap-3 px-4 lg:px-8">
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
          <nav
            aria-label="Primary navigation"
            className="hidden items-center gap-1 text-sm lg:flex"
          >
            {MAIN_LINKS.map((l) => (
              <Link
                key={l.href}
                href={l.href}
                aria-current={
                  isWorkspaceRoute(pathname, l.href) ? "page" : undefined
                }
                className="workspace-nav-link"
              >
                {l.label}
              </Link>
            ))}
            <NavGroup
              label="Research"
              items={RESEARCH_ITEMS}
              active={isWorkspaceRoute(pathname, "/research")}
            />
            <Link
              href="/copilot"
              aria-current={
                isWorkspaceRoute(pathname, "/copilot") ? "page" : undefined
              }
              className="workspace-nav-link"
            >
              Copilot
            </Link>
            <AccountMenu />
          </nav>
          {/* Mobile nav */}
          <MobileNav />
        </div>
        <MarketStatusBar />
        <PortfolioContextBar />
      </header>
      <main
        id="workspace-content"
        tabIndex={-1}
        className="mx-auto min-w-0 max-w-[1400px] px-4 pb-24 pt-7 outline-none lg:px-8 lg:pt-10"
      >
        {children}
      </main>
      <nav
        aria-label="Mobile primary navigation"
        className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-5 border-t border-border bg-card/95 px-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] pt-2 backdrop-blur-xl lg:hidden"
      >
        {WORKSPACE_LINKS.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            aria-current={
              isWorkspaceRoute(pathname, item.href) ? "page" : undefined
            }
            className="flex min-h-12 min-w-0 flex-col items-center justify-center gap-1 rounded-xl text-[11px] font-medium text-muted-foreground aria-[current=page]:bg-primary/10 aria-[current=page]:text-primary"
          >
            <WorkspaceIcon name={item.icon} />
            {item.label}
          </Link>
        ))}
      </nav>
      <FloatingCopilot />
      <FeedbackWidget />
    </div>
  );
}

function NavGroup({
  label,
  items,
  active,
}: {
  label: string;
  items: NavItem[];
  active?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const ref = useDismiss(open, () => setOpen(false), triggerRef);
  return (
    <div ref={ref} className="relative">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        data-active={active || undefined}
        className="workspace-nav-link flex items-center gap-1 data-[active=true]:bg-primary/10 data-[active=true]:text-primary"
      >
        {label}
        <span aria-hidden className="text-[10px] opacity-70">
          ▾
        </span>
      </button>
      {open && (
        <div className="absolute left-0 z-50 mt-1 min-w-44 rounded-md border border-border bg-card p-1 shadow-lg">
          {items.map((it) => (
            <MenuLink
              key={it.href}
              item={it}
              onNavigate={() => setOpen(false)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function MenuLink({
  item,
  onNavigate,
}: {
  item: NavItem;
  onNavigate: () => void;
}) {
  const cls =
    "block rounded px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent hover:text-accent-foreground";
  if (item.external) {
    return (
      <a href={item.href} className={cls} onClick={onNavigate}>
        {item.label}
      </a>
    );
  }
  return (
    <Link href={item.href} className={cls} onClick={onNavigate}>
      {item.label}
    </Link>
  );
}

function MobileNav() {
  const { user, configured, signOut } = useAuth();
  const billing = useBillingMe();
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const ref = useDismiss(open, () => setOpen(false), triggerRef);
  const close = () => setOpen(false);
  const isOwner = billing.data?.plan === "owner";

  return (
    <div ref={ref} className="relative lg:hidden">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label="Menu"
        className="flex h-11 w-11 items-center justify-center rounded-md border border-border text-foreground hover:bg-accent"
      >
        <span aria-hidden className="text-lg leading-none">
          {open ? "✕" : "☰"}
        </span>
      </button>
      {open && (
        <div className="absolute right-0 z-50 mt-2 max-h-[calc(100dvh-10rem-env(safe-area-inset-bottom))] w-60 overflow-y-auto overscroll-contain rounded-md border border-border bg-card p-2 shadow-lg [&_a]:min-h-11 [&_button]:min-h-11">
          {MAIN_LINKS.map((it) => (
            <MenuLink key={it.href} item={it} onNavigate={close} />
          ))}
          <Section label="Research" items={RESEARCH_ITEMS} onNavigate={close} />
          <MenuLink
            item={{ href: "/copilot", label: "Copilot" }}
            onNavigate={close}
          />
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
              <MenuLink
                item={{ href: "/login", label: "Sign in" }}
                onNavigate={close}
              />
              <MenuLink
                item={{ href: "/signup", label: "Sign up" }}
                onNavigate={close}
              />
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
  const triggerRef = useRef<HTMLButtonElement>(null);
  const ref = useDismiss(open, () => setOpen(false), triggerRef);

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
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
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
        <div className="absolute right-0 z-50 mt-1 min-w-48 rounded-md border border-border bg-card p-1 shadow-lg">
          {accountLinks(isOwner).map((it) => (
            <MenuLink
              key={it.href}
              item={it}
              onNavigate={() => setOpen(false)}
            />
          ))}
          <button
            type="button"
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
