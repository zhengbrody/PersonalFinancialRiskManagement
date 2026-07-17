import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MarketPageSwitcher } from "./market-page-switcher";

describe("MarketPageSwitcher", () => {
  it("separates the near-term signal from the live market desk", () => {
    render(<MarketPageSwitcher active="signal" />);

    expect(screen.getByText("Is elevated volatility becoming more likely?")).toBeInTheDocument();
    expect(screen.getByText("What is moving right now?")).toBeInTheDocument();
    expect(screen.getByText("You are here").closest("div[aria-current='page']")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Markets/i })).toHaveAttribute("href", "/markets");
  });

  it("links back to the model signal from Markets", () => {
    render(<MarketPageSwitcher active="desk" />);
    expect(screen.getByRole("link", { name: /Risk Today/i })).toHaveAttribute(
      "href",
      "/risk-today",
    );
  });
});
