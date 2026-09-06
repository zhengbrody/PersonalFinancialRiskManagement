"use client";

/**
 * App-wide floating Portfolio Copilot.
 *
 * A persistent bottom-right launcher that opens a chat panel, so a
 * signed-in user can ask the Copilot from ANY page without navigating to
 * /copilot. The panel renders the exact same <CopilotConversation /> that
 * powers the full page (DRY) — only the `variant="floating"` chrome differs.
 *
 * UX: the panel is **draggable by its header** (so it never sits where it's
 * in the way) and has a **maximize toggle** for reading longer, table-rich
 * answers. Default sits bottom-right.
 *
 * Visibility: only mounts for signed-in users on a configured build; hidden
 * on the dedicated /copilot route. Escape closes. Semantic theme tokens only
 * (reads correctly in the market-synced light/dark theme). No drag library —
 * a small pointer handler keeps the bundle lean.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { CopilotConversation } from "@/components/copilot-conversation";
import { useAuth } from "@/lib/auth-context";

type Pos = { x: number; y: number };

export function FloatingCopilot() {
  const { user, configured } = useAuth();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [maximized, setMaximized] = useState(false);
  const [pos, setPos] = useState<Pos | null>(null); // null = default bottom-right anchor
  const panelRef = useRef<HTMLDivElement>(null);
  const drag = useRef<{ offsetX: number; offsetY: number } | null>(null);

  // Close on Escape.
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const clamp = useCallback((x: number, y: number): Pos => {
    const el = panelRef.current;
    const w = el?.offsetWidth ?? 440;
    const h = el?.offsetHeight ?? 640;
    const maxX = Math.max(0, window.innerWidth - w);
    const maxY = Math.max(0, window.innerHeight - h);
    return {
      x: Math.min(Math.max(0, x), maxX),
      y: Math.min(Math.max(0, y), maxY),
    };
  }, []);

  // Keep dragged panels reachable after reopening, maximizing or resizing.
  // Compact screens use the full Copilot route; CSS hides BOTH floating surfaces
  // at the same breakpoint, preserving the conversation when returning to desktop.
  useEffect(() => {
    if (!open) return;
    const reposition = () => setPos((p) => (p ? clamp(p.x, p.y) : p));
    reposition();
    window.addEventListener("resize", reposition);
    return () => window.removeEventListener("resize", reposition);
  }, [open, maximized, clamp]);

  function onHeaderPointerDown(e: React.PointerEvent) {
    // Don't start a drag from the close/maximize buttons.
    if ((e.target as HTMLElement).closest("button")) return;
    const el = panelRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    drag.current = {
      offsetX: e.clientX - rect.left,
      offsetY: e.clientY - rect.top,
    };
    // Seed pos from the current rect so it doesn't jump from the anchor.
    setPos(clamp(rect.left, rect.top));
    try {
      (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    } catch {
      /* jsdom / unsupported — drag still works via window listeners below */
    }
  }

  useEffect(() => {
    function onMove(e: PointerEvent) {
      if (!drag.current) return;
      setPos(
        clamp(
          e.clientX - drag.current.offsetX,
          e.clientY - drag.current.offsetY,
        ),
      );
    }
    function onUp() {
      drag.current = null;
    }
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, [clamp]);

  // Anonymous visitors / unconfigured builds: render nothing.
  if (!configured || !user) return null;
  // Avoid two chats on the dedicated page.
  if (pathname === "/copilot") return null;

  const size = maximized
    ? "w-[min(96vw,720px)] h-[85vh]"
    : "w-[min(94vw,440px)] h-[min(78vh,640px)]";
  const anchor = pos ? "" : "bottom-20 right-4";
  const style = pos ? { left: pos.x, top: pos.y } : undefined;

  return (
    <>
      {open && (
        <div
          ref={panelRef}
          role="dialog"
          aria-label="Portfolio Copilot"
          aria-modal="false"
          style={style}
          className={`fixed ${anchor} ${size} z-50 hidden flex-col overflow-hidden rounded-2xl border border-border bg-card text-card-foreground shadow-xl lg:flex`}
        >
          <div
            onPointerDown={onHeaderPointerDown}
            className="flex cursor-move touch-none select-none items-center justify-between border-b border-border px-4 py-3"
          >
            <div className="flex items-center gap-2">
              <span className="inline-block h-2 w-2 rounded-full bg-primary" />
              <span className="text-sm font-semibold tracking-tight">
                Portfolio Copilot
              </span>
            </div>
            <div className="flex items-center gap-1">
              <button
                type="button"
                aria-label={
                  maximized ? "Restore Copilot size" : "Maximize Copilot"
                }
                onClick={() => setMaximized((v) => !v)}
                className="rounded-md px-2 py-0.5 text-sm leading-none text-muted-foreground transition hover:bg-accent hover:text-accent-foreground"
              >
                {maximized ? "❐" : "▢"}
              </button>
              <button
                type="button"
                aria-label="Close Copilot"
                onClick={() => setOpen(false)}
                className="rounded-md px-2 py-0.5 text-lg leading-none text-muted-foreground transition hover:bg-accent hover:text-accent-foreground"
              >
                ×
              </button>
            </div>
          </div>

          <CopilotConversation variant="floating" />
        </div>
      )}

      <button
        type="button"
        aria-label={open ? "Close Copilot" : "Ask Copilot"}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="fixed bottom-4 right-4 z-50 hidden h-12 items-center gap-2 rounded-full bg-primary px-4 text-sm font-medium text-primary-foreground shadow-lg transition hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background lg:flex"
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
