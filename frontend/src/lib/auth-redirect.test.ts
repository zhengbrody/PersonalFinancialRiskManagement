import { afterEach, describe, expect, it } from "vitest";
import {
  authHref,
  consumeAuthRedirect,
  readAuthRedirect,
  rememberAuthRedirect,
  safeAuthRedirect,
} from "./auth-redirect";

afterEach(() => {
  window.history.replaceState({}, "", "/");
  window.sessionStorage.clear();
});

describe("auth redirect intent", () => {
  it("accepts only explicit internal destinations", () => {
    expect(safeAuthRedirect("/portfolios/new", "/")).toBe("/portfolios/new");
    expect(safeAuthRedirect("/copilot", "/")).toBe("/copilot");
    expect(safeAuthRedirect("/analyze?view=stress", "/")).toBe(
      "/analyze?view=stress",
    );
    expect(safeAuthRedirect("https://evil.example", "/")).toBe("/");
    expect(safeAuthRedirect("//evil.example", "/")).toBe("/");
    expect(safeAuthRedirect("/portfolios/new?holdings=SPY", "/")).toBe("/");
    expect(safeAuthRedirect("/copilot?q=show%20my%20holdings", "/")).toBe("/");
    expect(safeAuthRedirect("/analyze?view=stress&ticker=NVDA", "/")).toBe("/");
    expect(safeAuthRedirect("/analyze?view=unknown", "/")).toBe("/");
  });

  it("round-trips a safe same-tab intent and consumes it once", () => {
    rememberAuthRedirect("/portfolios/new", "/");
    expect(readAuthRedirect("/")).toBe("/portfolios/new");
    expect(consumeAuthRedirect("/")).toBe("/portfolios/new");
    expect(readAuthRedirect("/")).toBe("/");
  });

  it("fails closed when the URL contains an untrusted next value", () => {
    rememberAuthRedirect("/portfolios/new", "/");
    window.history.replaceState({}, "", "/login?next=https%3A%2F%2Fevil.example");
    expect(readAuthRedirect("/")).toBe("/");
  });

  it("encodes only the destination, never portfolio contents", () => {
    expect(authHref("/signup", "/portfolios/new")).toBe(
      "/signup?next=%2Fportfolios%2Fnew",
    );
    expect(authHref("/login", "/analyze?view=stress")).toBe(
      "/login?next=%2Fanalyze%3Fview%3Dstress",
    );
  });
});
