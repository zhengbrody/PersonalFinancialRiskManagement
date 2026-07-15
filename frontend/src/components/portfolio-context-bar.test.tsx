/**
 * PortfolioContextBar — always shows the current book, lists books to switch,
 * and stays hidden until there's something to show.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithQuery } from "@/test-utils";

const switchPortfolioMock = vi.fn();
const ctx = {
  current: { id: "p1", name: "Book A", holdings: { SPY: {}, BND: {} }, updated_at: "2026-07-01T00:00:00Z" },
  list: [
    { id: "p1", name: "Book A", holdings: { SPY: {}, BND: {} } },
    { id: "p2", name: "Book B", holdings: {} },
  ],
  isLoading: false,
  switchingId: null as string | null,
  dataAsOf: "2026-07-01T00:00:00Z",
  switchPortfolio: switchPortfolioMock,
  pendingSwitchId: null as string | null,
  confirmDiscardAndSwitch: vi.fn(),
  cancelSwitch: vi.fn(),
} as unknown;
const authState = { user: { id: "u1" } as { id: string } | null };

vi.mock("@/lib/portfolio-context", () => ({ usePortfolioContext: () => ctx }));
vi.mock("@/lib/auth-context", () => ({ useAuth: () => authState }));

import { PortfolioContextBar } from "./portfolio-context-bar";

beforeEach(() => {
  switchPortfolioMock.mockReset();
  authState.user = { id: "u1" };
});
afterEach(() => vi.restoreAllMocks());

describe("PortfolioContextBar", () => {
  it("shows the current book name and holdings count", () => {
    renderWithQuery(<PortfolioContextBar />);
    expect(screen.getByText("Book A")).toBeInTheDocument();
    expect(screen.getByText(/2 holdings/)).toBeInTheDocument();
  });

  it("lists both books and switches on click of the inactive one", async () => {
    const user = userEvent.setup();
    renderWithQuery(<PortfolioContextBar />);
    await user.click(screen.getByRole("button", { name: /Book A/ }));
    // both books appear in the listbox; Book B is the switch target
    const options = screen.getAllByRole("option");
    expect(options.length).toBe(2);
    await user.click(screen.getByRole("option", { name: /Book B/ }));
    expect(switchPortfolioMock).toHaveBeenCalledWith("p2");
  });

  it("renders nothing when signed out", () => {
    authState.user = null;
    const { container } = renderWithQuery(<PortfolioContextBar />);
    expect(container.innerHTML).toBe("");
  });
});
