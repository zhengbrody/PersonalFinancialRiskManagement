"use client";

import { useEffect, useState } from "react";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

const mintSchema = z.strictObject({
  token: z.string(),
  expires_at: z.number().int(),
  share_path: z.string(),
});
const capabilitySchema = z.strictObject({ enabled: z.boolean() });

export function ShareRiskCardButton() {
  const { accessToken } = useAuth();
  const [pending, setPending] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [enabled, setEnabled] = useState(false);

  useEffect(() => {
    let active = true;
    void apiFetch("/api/v1/share_cards/capability", { schema: capabilitySchema })
      .then((result) => {
        if (active) setEnabled(result.enabled);
      })
      .catch(() => {
        if (active) setEnabled(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function share() {
    if (!accessToken) return;
    setPending(true);
    setStatus(null);
    try {
      const result = await apiFetch("/api/v1/share_cards/mint", {
        method: "POST",
        body: {},
        authToken: accessToken,
        schema: mintSchema,
      });
      const url = new URL(result.share_path, window.location.origin).toString();
      if (navigator.share) {
        await navigator.share({ title: "My MindMarket risk profile", url });
        setStatus("Shared");
      } else if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(url);
        setStatus("Privacy-safe share link copied");
      } else {
        window.open(url, "_blank", "noopener,noreferrer");
        setStatus("Share card opened");
      }
    } catch (error) {
      if ((error as Error)?.name !== "AbortError") {
        setStatus("Could not create a share link. Try again.");
      }
    } finally {
      setPending(false);
    }
  }

  if (!accessToken || !enabled) return null;
  return (
    <div className="flex items-center gap-2">
      <Button type="button" variant="outline" size="sm" disabled={pending} onClick={() => void share()}>
        {pending ? "Creating…" : "Share risk profile"}
      </Button>
      {status && <span className="text-xs text-muted-foreground" role="status">{status}</span>}
    </div>
  );
}
