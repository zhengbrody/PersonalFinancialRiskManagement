"use client";

/**
 * App-wide beta feedback widget (signed-in only). A discreet bottom-left pill
 * opens a small composer; submitting POSTs to /api/v1/feedback (which routes
 * to Sentry + logs) with the current page as context. Bottom-LEFT so it never
 * collides with the bottom-right floating Copilot.
 */

import { useState } from "react";
import { usePathname } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

type Status = "idle" | "sending" | "sent" | "error";

export function FeedbackWidget() {
  const { user, accessToken, configured } = useAuth();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [status, setStatus] = useState<Status>("idle");

  // Beta feedback is attributable → signed-in users only.
  if (!configured || !user) return null;

  function close() {
    setOpen(false);
    // Reset after the close animation so a reopen is fresh.
    setTimeout(() => {
      setText("");
      setStatus("idle");
    }, 200);
  }

  async function send() {
    const message = text.trim();
    if (!message || status === "sending") return;
    setStatus("sending");
    try {
      await apiFetch("/api/v1/feedback", {
        method: "POST",
        body: { message, context: pathname ?? "" },
        authToken: accessToken ?? undefined,
        allowNull: true,
      });
      setStatus("sent");
      setTimeout(close, 1200);
    } catch {
      setStatus("error");
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="relative mb-24 ml-4 rounded-full border border-border bg-card px-3 py-2 text-xs font-medium text-muted-foreground shadow-sm transition hover:bg-accent hover:text-accent-foreground lg:fixed lg:bottom-4 lg:left-4 lg:z-40 lg:m-0"
      >
        Feedback
      </button>

      {open && (
        <div
          className="fixed inset-0 z-[60] flex items-end justify-start bg-black/40 p-4 sm:items-center sm:justify-center"
          onClick={close}
        >
          <div
            className="w-full max-w-sm rounded-xl border border-border bg-card p-4 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-sm font-semibold">Send feedback</h2>
              <button
                type="button"
                onClick={close}
                aria-label="Close"
                className="rounded px-1.5 text-lg leading-none text-muted-foreground hover:text-foreground"
              >
                ✕
              </button>
            </div>
            {status === "sent" ? (
              <p className="py-4 text-center text-sm text-emerald-600 dark:text-emerald-400">
                Thanks — we read every note. 🙏
              </p>
            ) : (
              <>
                <p className="mb-2 text-xs text-muted-foreground">
                  Found a bug, something confusing, or an idea? Tell us — it goes
                  straight to the team.
                </p>
                <Textarea
                  aria-label="Your feedback"
                  rows={4}
                  placeholder="What's working, what's not…"
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  autoFocus
                />
                {status === "error" && (
                  <p className="mt-1 text-xs text-red-500">
                    Couldn&apos;t send — try again in a moment.
                  </p>
                )}
                <div className="mt-3 flex justify-end gap-2">
                  <Button type="button" variant="ghost" size="sm" onClick={close}>
                    Cancel
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    disabled={text.trim() === "" || status === "sending"}
                    onClick={send}
                  >
                    {status === "sending" ? "Sending…" : "Send"}
                  </Button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
