"use client";

/**
 * App-wide floating Portfolio Copilot.
 *
 * A persistent bottom-right launcher that opens a compact chat panel,
 * so a signed-in user can ask the Copilot a question from ANY page
 * without navigating to /copilot. The panel renders the exact same
 * <CopilotConversation /> that powers the full page (DRY) — only the
 * `variant="floating"` chrome differs.
 *
 * Visibility rules:
 *   • Only mounts for signed-in users on a configured build
 *     (`user && configured`). Anonymous/public visitors see nothing.
 *   • Hidden on the dedicated /copilot route so there aren't two chats
 *     at once.
 *
 * No dialog library: a fixed div + local open state is enough, and it
 * keeps the bundle lean. Escape closes the panel. Semantic theme tokens
 * only, so it reads correctly in the light/dark market-synced theme.
 */

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { CopilotConversation } from "@/components/copilot-conversation";
import { useAuth } from "@/lib/auth-context";

export function FloatingCopilot() {
  const { user, configured } = useAuth();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  // Close on Escape for keyboard users. Registered unconditionally
  // (hooks can't be conditional); the listener is cheap and only acts
  // when the panel is open.
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // Anonymous visitors / unconfigured builds: render nothing.
  if (!configured || !user) return null;

  // Avoid two chats on the dedicated page.
  if (pathname === "/copilot") return null;

  return (
    <>
      {open && (
        <div
          role="dialog"
          aria-label="Portfolio Copilot"
          aria-modal="false"
          className="fixed bottom-20 right-4 z-50 flex h-[min(70vh,560px)] w-[min(92vw,400px)] flex-col overflow-hidden rounded-2xl border border-border bg-card text-card-foreground shadow-xl"
        >
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <div className="flex items-center gap-2">
              <span className="inline-block h-2 w-2 rounded-full bg-primary" />
              <span className="text-sm font-semibold tracking-tight">
                Portfolio Copilot
              </span>
            </div>
            <button
              type="button"
              aria-label="Close Copilot"
              onClick={() => setOpen(false)}
              className="rounded-md px-2 py-0.5 text-lg leading-none text-muted-foreground transition hover:bg-accent hover:text-accent-foreground"
            >
              ×
            </button>
          </div>

          <CopilotConversation variant="floating" />
        </div>
      )}

      <button
        type="button"
        aria-label={open ? "Close Copilot" : "Ask Copilot"}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="fixed bottom-4 right-4 z-50 flex h-12 items-center gap-2 rounded-full bg-primary px-4 text-sm font-medium text-primary-foreground shadow-lg transition hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
      >
        <ChatGlyph />
        <span className="hidden sm:inline">
          {open ? "Close" : "Ask Copilot"}
        </span>
      </button>
    </>
  );
}

function ChatGlyph() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-5 w-5"
    >
      <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
    </svg>
  );
}
