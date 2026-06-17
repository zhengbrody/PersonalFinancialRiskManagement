import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ApiBalanceCard } from "./api-balance-card";
import type { AdminBalances, BalanceProvider } from "@/lib/queries";

// The card's Claude tile has an inline top-up editor (a mutation hook) — stub it.
const { mutate } = vi.hoisted(() => ({ mutate: vi.fn() }));
vi.mock("@/lib/queries", () => ({
  useSetAnthropicTopup: () => ({ mutate, isPending: false, isError: false }),
}));

const prov = (over: Partial<BalanceProvider>): BalanceProvider => ({
  provider: "DeepSeek",
  configured: true,
  source: "live",
  status: "ok",
  ...over,
});

const data = (over: Partial<AdminBalances> = {}): AdminBalances => ({
  deepseek: prov({ provider: "DeepSeek", source: "live", currency: "CNY", remaining: 88.5, topped_up: 100 }),
  anthropic: prov({
    provider: "Claude (Anthropic)",
    source: "estimate",
    currency: "USD",
    remaining: 17.5,
    topped_up: 20,
    spent: 2.5,
  }),
  ...over,
});

describe("ApiBalanceCard", () => {
  it("shows both providers with remaining + live/estimate chips", () => {
    render(<ApiBalanceCard data={data()} loading={false} />);
    expect(screen.getByText("DeepSeek")).toBeInTheDocument();
    expect(screen.getByText("Claude (Anthropic)")).toBeInTheDocument();
    expect(screen.getByText("88.50 CNY")).toBeInTheDocument(); // DeepSeek live, foreign currency
    expect(screen.getByText("$17.50")).toBeInTheDocument(); // Claude estimate, USD
    expect(screen.getByText("live")).toBeInTheDocument();
    expect(screen.getByText("estimate")).toBeInTheDocument();
  });

  it("surfaces a low-balance warning when a provider is low", () => {
    render(
      <ApiBalanceCard
        data={data({
          deepseek: prov({ status: "critical", low: true, currency: "USD", remaining: 1, topped_up: 50 }),
        })}
        loading={false}
      />,
    );
    expect(screen.getByText(/低余量/)).toBeInTheDocument();
  });

  it("hints how to configure an unconfigured Claude top-up", () => {
    render(
      <ApiBalanceCard
        data={data({
          anthropic: prov({ provider: "Claude (Anthropic)", source: "estimate", configured: false, status: "unknown" }),
        })}
        loading={false}
      />,
    );
    expect(screen.getByText(/ANTHROPIC_TOPUP_USD/)).toBeInTheDocument();
  });

  it("lets the owner set the Claude balance inline (no env / restart)", () => {
    render(<ApiBalanceCard data={data()} loading={false} />);
    fireEvent.click(screen.getByText("✎ 充值后更新余额"));
    fireEvent.change(screen.getByPlaceholderText("新余额 $"), { target: { value: "30" } });
    fireEvent.click(screen.getByText("保存"));
    expect(mutate).toHaveBeenCalledWith(30, expect.anything());
  });

  it("renders nothing without data", () => {
    const { container } = render(<ApiBalanceCard data={undefined} loading={false} />);
    expect(container).toBeEmptyDOMElement();
  });
});
