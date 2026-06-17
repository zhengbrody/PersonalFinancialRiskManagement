import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ApiBalanceCard } from "./api-balance-card";
import type { AdminBalances, BalanceProvider } from "@/lib/queries";

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

  it("renders nothing without data", () => {
    const { container } = render(<ApiBalanceCard data={undefined} loading={false} />);
    expect(container).toBeEmptyDOMElement();
  });
});
