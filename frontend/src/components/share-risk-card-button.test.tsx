import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { apiFetchMock } = vi.hoisted(() => ({ apiFetchMock: vi.fn() }));

vi.mock("@/lib/api", () => ({ apiFetch: (...args: unknown[]) => apiFetchMock(...args) }));
vi.mock("@/lib/auth-context", () => ({ useAuth: () => ({ accessToken: "jwt" }) }));

import { ShareRiskCardButton } from "./share-risk-card-button";

beforeEach(() => {
  apiFetchMock.mockReset();
  Object.defineProperty(navigator, "share", { configurable: true, value: undefined });
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
  });
});

describe("ShareRiskCardButton", () => {
  it("mints a server-derived link only when the deployment supports sharing", async () => {
    apiFetchMock
      .mockResolvedValueOnce({ enabled: true })
      .mockResolvedValueOnce({
        token: "signed-token",
        expires_at: 1_800_000_000,
        share_path: "/share/risk-card?token=signed-token",
      });
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    render(<ShareRiskCardButton />);

    await user.click(await screen.findByRole("button", { name: /share risk profile/i }));

    expect(apiFetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/v1/share_cards/mint",
      expect.objectContaining({ method: "POST", body: {}, authToken: "jwt" }),
    );
    expect(writeText).toHaveBeenCalledWith(
      expect.stringContaining("/share/risk-card?token=signed-token"),
    );
    expect(screen.getByRole("status")).toHaveTextContent(/privacy-safe share link copied/i);
  });

  it("renders no misleading action when the signing capability is unavailable", async () => {
    apiFetchMock.mockResolvedValueOnce({ enabled: false });
    render(<ShareRiskCardButton />);
    await vi.waitFor(() => expect(apiFetchMock).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("button", { name: /share risk profile/i })).not.toBeInTheDocument();
  });
});
