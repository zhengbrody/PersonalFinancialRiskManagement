import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ScoreGauge } from "./score-gauge";

describe("ScoreGauge", () => {
  it("exposes the score and band without relying on color", () => {
    render(<ScoreGauge score={782} />);
    const meter = screen.getByRole("meter", { name: "Portfolio health score" });
    expect(meter).toHaveAttribute("aria-valuenow", "782");
    expect(meter).toHaveAttribute("aria-valuetext", "782 of 1000, Healthy");
  });
  it("places the scale labels at their actual band boundaries", () => {
    render(<ScoreGauge score={650} />);
    expect(screen.getByText("400")).toHaveClass("left-[40%]");
    expect(screen.getByText("650")).toHaveClass("left-[65%]");
    expect(screen.getByText("850")).toHaveClass("left-[85%]");
  });
});
