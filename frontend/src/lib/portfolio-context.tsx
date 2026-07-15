"use client";

/**
 * Global "active portfolio" context — the single source of truth for WHICH book
 * every signed-in surface analyzes. The active book is the row with
 * is_default=true (most-recent fallback), exactly as the backend resolves it.
 *
 * A switch is ONE atomic server operation (POST /portfolios/{id}/activate,
 * migration 0011), after which this context:
 *   1. cancels in-flight portfolio-dependent queries (a late response can't
 *      paint the old book under the new label),
 *   2. RESETS the portfolio-scoped caches (no stale flash — surfaces show a
 *      loading state, never the prior book's numbers),
 *   3. refetches the portfolio list so is_default reflects server truth,
 *   4. broadcasts to the account's other tabs (BroadcastChannel) so they resync.
 *
 * Copilot conversation / saved answer / insight dismissals are keyed by
 * `${...}:${activePortfolioId}` in their own components, so a switch isolates
 * them without this context touching storage. Cross-USER isolation stays with
 * `user-scoped-storage` (wiped on identity change / sign-out).
 *
 * An unsaved-analysis guard registry lets a surface (the what-if lab, PR3)
 * block a switch until the user saves/discards; PR1 ships the mechanism.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { type QueryClient, type QueryKey, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "./auth-context";
import { track } from "./analytics";
import { type PortfolioRow, useActivatePortfolio, useMyPortfolios } from "./queries";

// Cached queries whose payload depends on the ACTIVE book. A switch resets
// every query whose key STARTS WITH one of these (React Query partial match),
// so nothing from the prior portfolio survives under the new one. NOT included:
// ["copilot-preferences"] (user-level memory, identical across books) and any
// ticker/macro/public key (portfolio-independent).
export const PORTFOLIO_SCOPED_RESET_KEYS: QueryKey[] = [
  ["risk"], // score_active · last_snapshot · snapshot_history · simulate_actions · alerts · explain · score_changes (+ cheap public benchmarks refetch)
  ["institutions", "smart_money"],
  ["copilot-insights"],
  ["options-analyze"],
  ["options-explain"],
];

const CHANNEL_NAME = "mm:portfolio";

type SwitchMessage = { type: "switch"; userId: string; portfolioId: string };

export type PortfolioContextValue = {
  /** The active book (is_default, most-recent fallback), or null. */
  current: PortfolioRow | null;
  /** All the caller's books, default-first. */
  list: PortfolioRow[];
  /** `current?.id ?? null` — the id every *_from_active endpoint resolves. */
  activePortfolioId: string | null;
  /** True while the portfolios list is loading for the first time. */
  isLoading: boolean;
  hasPortfolios: boolean;
  /** The id currently being switched to (drives per-row spinners), or null. */
  switchingId: string | null;
  /** Atomically switch the active book. Respects unsaved-analysis guards
   *  unless `{ force: true }`; a blocked switch sets `pendingSwitchId`. */
  switchPortfolio: (portfolioId: string, opts?: { force?: boolean }) => Promise<void>;
  /** A switch a guard blocked, awaiting the user's Discard/Stay choice. */
  pendingSwitchId: string | null;
  confirmDiscardAndSwitch: () => Promise<void>;
  cancelSwitch: () => void;
  /** Register a "do I have unsaved analysis?" predicate; returns an unregister. */
  registerUnsavedGuard: (id: string, isDirty: () => boolean) => () => void;
  hasUnsavedAnalysis: () => boolean;
};

const PortfolioContext = createContext<PortfolioContextValue | undefined>(undefined);

/** Reset every portfolio-scoped cache: cancel in-flight, drop cached data so no
 *  stale flash, then refresh the list. Shared by a local switch and a
 *  broadcast from another tab. */
async function applyPortfolioSwitch(qc: QueryClient, userId: string | null): Promise<void> {
  await Promise.all(
    PORTFOLIO_SCOPED_RESET_KEYS.map((key) => qc.cancelQueries({ queryKey: key })),
  );
  // resetQueries → active observers revert to loading and refetch for the NEW
  // book; inactive entries are cleared. No prior-book data can paint.
  PORTFOLIO_SCOPED_RESET_KEYS.forEach((key) => qc.resetQueries({ queryKey: key }));
  // Keep the list visible (invalidate, not reset) so the switcher never blanks.
  qc.invalidateQueries({ queryKey: ["portfolios", "me", userId ?? null] });
}

export function PortfolioProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const userId = user?.id ?? null;
  const qc = useQueryClient();
  const portfolios = useMyPortfolios();
  const activate = useActivatePortfolio();

  const [switchingId, setSwitchingId] = useState<string | null>(null);
  const [pendingSwitchId, setPendingSwitchId] = useState<string | null>(null);
  const guardsRef = useRef<Map<string, () => boolean>>(new Map());

  const list = useMemo(() => portfolios.data?.portfolios ?? [], [portfolios.data]);
  const current = useMemo(
    () => list.find((p) => p.is_default) ?? list[0] ?? null,
    [list],
  );
  const activePortfolioId = current?.id ?? null;

  // Keep a ref of the active id for the broadcast listener (avoids re-subscribing
  // on every switch).
  const activeIdRef = useRef<string | null>(activePortfolioId);
  useEffect(() => {
    activeIdRef.current = activePortfolioId;
  }, [activePortfolioId]);

  // The receiver's OWN channel — posting through it gives free self-exclusion
  // (BroadcastChannel never delivers a message to the object that sent it), so
  // the initiating tab can't re-process its own switch.
  const channelRef = useRef<BroadcastChannel | null>(null);

  const hasUnsavedAnalysis = useCallback(() => {
    for (const isDirty of guardsRef.current.values()) {
      try {
        if (isDirty()) return true;
      } catch {
        /* a broken guard must not wedge switching */
      }
    }
    return false;
  }, []);

  const registerUnsavedGuard = useCallback((id: string, isDirty: () => boolean) => {
    guardsRef.current.set(id, isDirty);
    return () => {
      guardsRef.current.delete(id);
    };
  }, []);

  const doSwitch = useCallback(
    async (portfolioId: string) => {
      setPendingSwitchId(null);
      setSwitchingId(portfolioId);
      try {
        await activate.mutateAsync(portfolioId);
        // Optimistic: flip is_default in the cached list so `current` (and the
        // bar) update instantly, before the invalidate refetch confirms it.
        qc.setQueryData(
          ["portfolios", "me", userId],
          (old: { portfolios: PortfolioRow[] } | undefined) =>
            old
              ? {
                  ...old,
                  portfolios: old.portfolios.map((p) => ({
                    ...p,
                    is_default: p.id === portfolioId,
                  })),
                }
              : old,
        );
        await applyPortfolioSwitch(qc, userId);
        // Notify the account's OTHER tabs (self-excluded by BroadcastChannel).
        if (userId) {
          channelRef.current?.postMessage({
            type: "switch",
            userId,
            portfolioId,
          } satisfies SwitchMessage);
        }
        track("portfolio_switched", {}); // id/name/ticker NEVER sent
      } catch {
        // Switch failed → resync the list to server truth (no optimistic lie).
        qc.invalidateQueries({ queryKey: ["portfolios", "me", userId] });
      } finally {
        setSwitchingId(null);
      }
    },
    [activate, qc, userId],
  );

  const switchPortfolio = useCallback(
    async (portfolioId: string, opts?: { force?: boolean }) => {
      if (!portfolioId || portfolioId === activeIdRef.current) return;
      if (!opts?.force && hasUnsavedAnalysis()) {
        setPendingSwitchId(portfolioId); // bar shows Discard/Stay
        return;
      }
      await doSwitch(portfolioId);
    },
    [doSwitch, hasUnsavedAnalysis],
  );

  const confirmDiscardAndSwitch = useCallback(async () => {
    const target = pendingSwitchId;
    if (target) await doSwitch(target);
  }, [pendingSwitchId, doSwitch]);

  const cancelSwitch = useCallback(() => setPendingSwitchId(null), []);

  // Cross-tab sync: another tab of the SAME account switched → resync here. We
  // POST through this same channel (see channelRef), so this handler never
  // fires for our OWN switch — no timing-dependent self-exclusion guard needed.
  useEffect(() => {
    if (typeof window === "undefined" || typeof BroadcastChannel === "undefined") return;
    const channel = new BroadcastChannel(CHANNEL_NAME);
    channelRef.current = channel;
    channel.onmessage = (event: MessageEvent<SwitchMessage>) => {
      const msg = event.data;
      if (msg?.type === "switch" && msg.userId === userId) {
        // The other tab already flipped is_default server-side; refetching the
        // list here updates `current`, and the reset clears this tab's stale
        // analysis so it re-fetches for the new book.
        void applyPortfolioSwitch(qc, userId);
      }
    };
    return () => {
      channelRef.current = null;
      channel.close();
    };
  }, [userId, qc]);

  const value = useMemo<PortfolioContextValue>(
    () => ({
      current,
      list,
      activePortfolioId,
      isLoading: portfolios.isLoading,
      hasPortfolios: list.length > 0,
      switchingId,
      switchPortfolio,
      pendingSwitchId,
      confirmDiscardAndSwitch,
      cancelSwitch,
      registerUnsavedGuard,
      hasUnsavedAnalysis,
    }),
    [
      current,
      list,
      activePortfolioId,
      portfolios.isLoading,
      switchingId,
      switchPortfolio,
      pendingSwitchId,
      confirmDiscardAndSwitch,
      cancelSwitch,
      registerUnsavedGuard,
      hasUnsavedAnalysis,
    ],
  );

  return <PortfolioContext.Provider value={value}>{children}</PortfolioContext.Provider>;
}

/**
 * Read the active-portfolio context. Safe to call anywhere under
 * `PortfolioProvider`; returns an inert default when no provider is mounted
 * (e.g. a unit test rendering a leaf in isolation) so components never crash.
 */
export function usePortfolioContext(): PortfolioContextValue {
  const ctx = useContext(PortfolioContext);
  if (ctx) return ctx;
  return INERT;
}

const INERT: PortfolioContextValue = {
  current: null,
  list: [],
  activePortfolioId: null,
  isLoading: false,
  hasPortfolios: false,
  switchingId: null,
  switchPortfolio: async () => {},
  pendingSwitchId: null,
  confirmDiscardAndSwitch: async () => {},
  cancelSwitch: () => {},
  registerUnsavedGuard: () => () => {},
  hasUnsavedAnalysis: () => false,
};
