import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const signOut = vi.fn().mockResolvedValue(undefined);
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ signOut, accessToken: "tok", user: { id: "u1" } }),
}));

const resetAnalytics = vi.fn();
vi.mock("@/lib/analytics", () => ({ resetAnalytics: () => resetAnalytics() }));

const mutate = vi.fn();
const resetMutation = vi.fn();
let mutationState: { isPending: boolean; isError: boolean; error: Error | null } = {
  isPending: false,
  isError: false,
  error: null,
};
vi.mock("@/lib/queries", () => ({
  useDeleteAccount: () => ({ mutate, reset: resetMutation, ...mutationState }),
}));

import { CONFIRMATION_PHRASE, DangerZoneCard } from "./danger-zone-card";

function renderCard() {
  const qc = new QueryClient();
  const clearSpy = vi.spyOn(qc, "clear");
  render(
    <QueryClientProvider client={qc}>
      <DangerZoneCard />
    </QueryClientProvider>,
  );
  return { clearSpy };
}

beforeEach(() => {
  vi.clearAllMocks();
  mutationState = { isPending: false, isError: false, error: null };
});

describe("DangerZoneCard", () => {
  it("requires the exact confirmation phrase before enabling deletion", () => {
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: /delete my account/i }));
    const confirm = screen.getByRole("button", { name: /permanently delete/i });
    expect(confirm).toBeDisabled();

    const input = screen.getByLabelText(/deletion confirmation phrase/i);
    fireEvent.change(input, { target: { value: "delete my account" } }); // wrong case
    expect(confirm).toBeDisabled();

    fireEvent.change(input, { target: { value: CONFIRMATION_PHRASE } });
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    expect(mutate).toHaveBeenCalledWith(CONFIRMATION_PHRASE, expect.anything());
  });

  it("on success clears the query cache, PostHog identity, session, then redirects home", async () => {
    const { clearSpy } = renderCard();
    fireEvent.click(screen.getByRole("button", { name: /delete my account/i }));
    fireEvent.change(screen.getByLabelText(/deletion confirmation phrase/i), {
      target: { value: CONFIRMATION_PHRASE },
    });
    fireEvent.click(screen.getByRole("button", { name: /permanently delete/i }));

    // fire the mutation's onSuccess callback
    const opts = mutate.mock.calls[0][1] as { onSuccess: () => Promise<void> };
    await opts.onSuccess();

    await waitFor(() => expect(push).toHaveBeenCalledWith("/"));
    expect(clearSpy).toHaveBeenCalled();
    expect(resetAnalytics).toHaveBeenCalled();
    expect(signOut).toHaveBeenCalled();
    expect(screen.getByText(/account deleted/i)).toBeInTheDocument();
  });

  it("surfaces a failed deletion without redirecting", () => {
    mutationState = {
      isPending: false,
      isError: true,
      error: new Error("Your subscription could not be canceled automatically"),
    };
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: /delete my account/i }));
    expect(screen.getByText(/subscription could not be canceled/i)).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });
});
