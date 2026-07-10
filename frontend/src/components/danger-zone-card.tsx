"use client";

/**
 * Settings danger zone — permanent account deletion (the Privacy Policy's
 * "delete your account and all associated data").
 *
 * Two-step confirmation: open the zone, then type the exact phrase. On
 * success every local trace is cleared — React Query cache, the Supabase
 * session, the PostHog identity — before redirecting home. The server side
 * is the authed DELETE /api/v1/account (self-only; fails closed if a live
 * subscription can't be canceled).
 */

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { resetAnalytics } from "@/lib/analytics";
import { useAuth } from "@/lib/auth-context";
import { useDeleteAccount } from "@/lib/queries";

export const CONFIRMATION_PHRASE = "DELETE MY ACCOUNT";

export function DangerZoneCard() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { signOut } = useAuth();
  const deletion = useDeleteAccount();
  const [open, setOpen] = useState(false);
  const [phrase, setPhrase] = useState("");
  const [done, setDone] = useState(false);

  const phraseOk = phrase.trim() === CONFIRMATION_PHRASE;

  async function onDelete() {
    deletion.mutate(phrase.trim(), {
      onSuccess: async () => {
        setDone(true);
        try {
          queryClient.clear(); // no cached portfolios/billing for the next user
          resetAnalytics(); // unlink the PostHog identity
          await signOut(); // drop the Supabase session
        } finally {
          router.push("/");
        }
      },
    });
  }

  if (done) {
    return (
      <Card className="border-destructive/40">
        <CardHeader>
          <CardTitle className="text-base">Account deleted</CardTitle>
          <CardDescription>
            Your account and all associated data have been removed. Redirecting…
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <Card className="border-destructive/40">
      <CardHeader>
        <CardTitle className="text-base text-destructive">Danger zone</CardTitle>
        <CardDescription>
          Permanently delete your account: profile, portfolios, score history, usage
          records, and email preferences. This cannot be undone. Deleted data also ages
          out of encrypted backups within 90 days. Export your portfolios first if you
          want a copy.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {!open ? (
          <Button type="button" variant="destructive" size="sm" onClick={() => setOpen(true)}>
            Delete my account…
          </Button>
        ) : (
          <div className="space-y-3">
            <p className="text-sm">
              Type <span className="font-mono font-semibold">{CONFIRMATION_PHRASE}</span> to
              confirm:
            </p>
            <Input
              value={phrase}
              onChange={(e) => setPhrase(e.target.value)}
              placeholder={CONFIRMATION_PHRASE}
              aria-label="Deletion confirmation phrase"
              className="max-w-xs font-mono"
            />
            <div className="flex gap-2">
              <Button
                type="button"
                variant="destructive"
                size="sm"
                disabled={!phraseOk || deletion.isPending}
                onClick={onDelete}
              >
                {deletion.isPending ? "Deleting…" : "Permanently delete"}
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={deletion.isPending}
                onClick={() => {
                  setOpen(false);
                  setPhrase("");
                  deletion.reset();
                }}
              >
                Cancel
              </Button>
            </div>
            {deletion.isError && (
              <p className="text-xs text-destructive">
                {(deletion.error as Error)?.message ?? "Deletion failed — nothing was removed."}
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
