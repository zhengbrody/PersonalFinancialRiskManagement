import { describe, expect, it, vi } from "vitest";

const redirectMock = vi.fn();
vi.mock("next/navigation", () => ({ redirect: (path: string) => redirectMock(path) }));

import PricingPage from "./page";

describe("retired pricing route", () => {
  it("redirects old links to the current product story", () => {
    PricingPage();
    expect(redirectMock).toHaveBeenCalledWith("/product");
  });
});
