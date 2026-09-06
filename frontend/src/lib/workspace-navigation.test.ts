import { describe, expect, it } from "vitest";
import { isWorkspaceRoute, WORKSPACE_LINKS } from "./workspace-navigation";

describe("workspace navigation", () => {
  it.each([
    ["/", "/"],
    ["/portfolios/p1/edit", "/portfolios"],
    ["/risk", "/analyze"],
    ["/score", "/analyze"],
    ["/analyze", "/analyze"],
    ["/markets", "/research"],
    ["/institutions", "/research"],
    ["/copilot", "/copilot"],
  ])("maps %s to exactly one primary destination", (pathname, expected) => {
    expect(
      WORKSPACE_LINKS.filter((item) =>
        isWorkspaceRoute(pathname, item.href),
      ).map((item) => item.href),
    ).toEqual([expected]);
  });
  it("does not falsely match path prefixes or account pages", () => {
    expect(isWorkspaceRoute("/portfolio-stress-test", "/portfolios")).toBe(
      false,
    );
    expect(
      WORKSPACE_LINKS.some((item) => isWorkspaceRoute("/settings", item.href)),
    ).toBe(false);
  });
});
