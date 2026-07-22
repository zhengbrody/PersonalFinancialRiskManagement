import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Tabs } from "./tabs";

const items = [
  { value: "overview", label: "Overview" },
  { value: "drivers", label: "Drivers" },
  { value: "stress", label: "Stress" },
];

describe("Tabs keyboard navigation", () => {
  it("moves focus and selection with arrows, Home and End", async () => {
    const onChange = vi.fn();
    render(
      <Tabs items={items} value="drivers" onValueChange={onChange} idBase="test" />,
    );
    const user = userEvent.setup();
    const drivers = screen.getByRole("tab", { name: "Drivers" });
    drivers.focus();

    await user.keyboard("{ArrowRight}");
    expect(onChange).toHaveBeenLastCalledWith("stress");
    expect(screen.getByRole("tab", { name: "Stress" })).toHaveFocus();

    await user.keyboard("{Home}");
    expect(onChange).toHaveBeenLastCalledWith("overview");
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveFocus();

    await user.keyboard("{End}");
    expect(onChange).toHaveBeenLastCalledWith("stress");
    expect(screen.getByRole("tab", { name: "Stress" })).toHaveFocus();
  });
});
