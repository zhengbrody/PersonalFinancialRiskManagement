/**
 * PortfolioContext — the atomic active-book switch and its side-effects:
 * activate → cancel + reset portfolio-scoped caches → refresh list → broadcast,
 * plus the unsaved-analysis guard and the delete-fallback contract.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient } from "@tanstack/react-query";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithQuery } from "@/test-utils";

const activateMutateAsync = vi.fn();
const portfoliosState: { data: unknown; isLoading: boolean } = {
  data: {
    portfolios: [
      { id: "p1", name: "Book A", is_default: true, holdings: { SPY: { shares: 1 } } },
      { id: "p2", name: "Book B", is_default: false, holdings: {} },
    ],
  },
  isLoading: false,
};
vi.mock("@/lib/queries", () => ({
  useMyPortfolios: () => portfoliosState,
  useActivatePortfolio: () => ({ mutateAsync: activateMutateAsync }),
}));
vi.mock("@/lib/auth-context", () => ({ useAuth: () => ({ user: { id: "u1" } }) }));
const trackMock = vi.fn();
vi.mock("@/lib/analytics", () => ({ track: (...a: unknown[]) => trackMock(...a) }));

// jsdom lacks BroadcastChannel in some setups — provide a spyable stub.
const postMessageMock = vi.fn();
beforeEach(() => {
  activateMutateAsync.mockReset().mockResolvedValue({ id: "p2", is_default: true });
  trackMock.mockReset();
  postMessageMock.mockReset();
  portfoliosState.data = {
    portfolios: [
      { id: "p1", name: "Book A", is_default: true, holdings: { SPY: { shares: 1 } } },
      { id: "p2", name: "Book B", is_default: false, holdings: {} },
    ],
  };
  // @ts-expect-error test stub
  globalThis.BroadcastChannel = class {
    postMessage = postMessageMock;
    close = vi.fn();
    onmessage: ((e: MessageEvent) => void) | null = null;
  };
});
afterEach(() => vi.restoreAllMocks());

import { PortfolioProvider, usePortfolioContext } from "./portfolio-context";

function Probe() {
  const ctx = usePortfolioContext();
  return (
    <div>
      <span data-testid="current">{ctx.current?.name ?? "none"}</span>
      <span data-testid="active-id">{ctx.activePortfolioId ?? "null"}</span>
      <span data-testid="pending">{ctx.pendingSwitchId ?? "none"}</span>
      <button onClick={() => void ctx.switchPortfolio("p2")}>switch-b</button>
      <button onClick={() => void ctx.confirmDiscardAndSwitch()}>confirm</button>
      <button onClick={() => ctx.cancelSwitch()}>cancel</button>
      <button onClick={() => ctx.registerUnsavedGuard("g", () => true)}>register-dirty</button>
    </div>
  );
}

describe("PortfolioContext switching", () => {
  it("derives the active book from is_default", () => {
    renderWithQuery(
      <PortfolioProvider>
        <Probe />
      </PortfolioProvider>,
    );
    expect(screen.getByTestId("current").textContent).toBe("Book A");
    expect(screen.getByTestId("active-id").textContent).toBe("p1");
  });

  it("switch activates, resets portfolio-scoped caches, broadcasts, and tracks", async () => {
    const resetSpy = vi.spyOn(QueryClient.prototype, "resetQueries");
    const cancelSpy = vi.spyOn(QueryClient.prototype, "cancelQueries");
    const user = userEvent.setup();
    renderWithQuery(
      <PortfolioProvider>
        <Probe />
      </PortfolioProvider>,
    );
    await user.click(screen.getByText("switch-b"));

    await waitFor(() => expect(activateMutateAsync).toHaveBeenCalledWith("p2"));
    // in-flight portfolio-dependent queries are cancelled, then reset so no
    // prior-book data can paint.
    const cancelledKeys = cancelSpy.mock.calls.map((c) => JSON.stringify(c[0]?.queryKey));
    const resetKeys = resetSpy.mock.calls.map((c) => JSON.stringify(c[0]?.queryKey));
    expect(cancelledKeys).toContain(JSON.stringify(["risk"]));
    expect(resetKeys).toContain(JSON.stringify(["risk"]));
    expect(resetKeys).toContain(JSON.stringify(["copilot-insights"]));
    expect(resetKeys).toContain(JSON.stringify(["options-analyze"]));
    // copilot-PREFERENCES are user-level, not portfolio-level → NOT reset.
    expect(resetKeys).not.toContain(JSON.stringify(["copilot-preferences"]));
    // cross-tab broadcast + a value-free analytics event.
    expect(postMessageMock).toHaveBeenCalledWith(
      expect.objectContaining({ type: "switch", userId: "u1", portfolioId: "p2" }),
    );
    expect(trackMock).toHaveBeenCalledWith("portfolio_switched", {});
  });

  it("switching to the already-active book is a no-op", async () => {
    const user = userEvent.setup();
    function OwnProbe() {
      const ctx = usePortfolioContext();
      return <button onClick={() => void ctx.switchPortfolio("p1")}>switch-a</button>;
    }
    renderWithQuery(
      <PortfolioProvider>
        <OwnProbe />
      </PortfolioProvider>,
    );
    await user.click(screen.getByText("switch-a"));
    expect(activateMutateAsync).not.toHaveBeenCalled();
  });

  it("an unsaved-analysis guard blocks the switch until confirmed", async () => {
    const user = userEvent.setup();
    renderWithQuery(
      <PortfolioProvider>
        <Probe />
      </PortfolioProvider>,
    );
    await user.click(screen.getByText("register-dirty"));
    await user.click(screen.getByText("switch-b"));
    // Blocked: no activate yet, pending switch is surfaced for the bar.
    expect(activateMutateAsync).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByTestId("pending").textContent).toBe("p2"));
    // Confirm → the switch proceeds.
    await user.click(screen.getByText("confirm"));
    await waitFor(() => expect(activateMutateAsync).toHaveBeenCalledWith("p2"));
  });

  it("cancel clears the pending switch without activating", async () => {
    const user = userEvent.setup();
    renderWithQuery(
      <PortfolioProvider>
        <Probe />
      </PortfolioProvider>,
    );
    await user.click(screen.getByText("register-dirty"));
    await user.click(screen.getByText("switch-b"));
    await waitFor(() => expect(screen.getByTestId("pending").textContent).toBe("p2"));
    await user.click(screen.getByText("cancel"));
    expect(screen.getByTestId("pending").textContent).toBe("none");
    expect(activateMutateAsync).not.toHaveBeenCalled();
  });

  it("a failed activate resyncs the list and does NOT broadcast", async () => {
    activateMutateAsync.mockRejectedValueOnce(new Error("boom"));
    const invalidateSpy = vi.spyOn(QueryClient.prototype, "invalidateQueries");
    const user = userEvent.setup();
    renderWithQuery(
      <PortfolioProvider>
        <Probe />
      </PortfolioProvider>,
    );
    await user.click(screen.getByText("switch-b"));
    await waitFor(() => expect(activateMutateAsync).toHaveBeenCalledWith("p2"));
    // No lie: the optimistic reset/broadcast/track never fire on failure; the
    // list is invalidated to reconverge on server truth.
    expect(postMessageMock).not.toHaveBeenCalled();
    expect(trackMock).not.toHaveBeenCalled();
    const invalidatedKeys = invalidateSpy.mock.calls.map((c) => JSON.stringify(c[0]?.queryKey));
    expect(invalidatedKeys).toContain(JSON.stringify(["portfolios", "me", "u1"]));
  });
});
