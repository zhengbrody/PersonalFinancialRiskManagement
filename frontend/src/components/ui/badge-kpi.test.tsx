import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Kpi } from "./kpi";
import { Badge } from "./badge";

describe("Kpi", () => {
  it("renders label + value, neutral tone by default", () => {
    render(<Kpi label="Annual vol" value="24.3%" />);
    expect(screen.getByText("Annual vol")).toBeInTheDocument();
    expect(screen.getByText("24.3%")).toHaveClass("text-foreground");
  });

  it("tone colors the value with the risk palette", () => {
    render(<Kpi label="VaR 95" value="-2.5%" tone="bad" />);
    expect(screen.getByText("-2.5%")).toHaveClass("text-destructive");
  });

  it("delta: positive is success; deltaInvert flips the meaning", () => {
    const { rerender } = render(<Kpi label="x" value="1" delta={5} />);
    expect(screen.getByText("+5")).toHaveClass("text-success");
    rerender(<Kpi label="x" value="1" delta={5} deltaInvert />);
    expect(screen.getByText("+5")).toHaveClass("text-destructive");
  });
});

describe("Badge", () => {
  it("renders children tinted by tone", () => {
    render(<Badge tone="primary">Pro</Badge>);
    const b = screen.getByText("Pro");
    expect(b).toHaveClass("text-primary");
    expect(b).toHaveClass("bg-primary/10");
  });

  it("uppercase adds wide tracking", () => {
    render(
      <Badge tone="neutral" uppercase>
        alpha
      </Badge>,
    );
    expect(screen.getByText("alpha")).toHaveClass("uppercase");
  });
});
