import { describe, it, expect } from "vitest";
import { displayName, currentUsername } from "./user-display";

const withMeta = (username?: unknown) =>
  ({ user_metadata: username === undefined ? {} : { username } }) as {
    user_metadata: Record<string, unknown>;
  };

describe("displayName", () => {
  it("returns the chosen username when set", () => {
    expect(displayName(withMeta("Alex Chen"))).toBe("Alex Chen");
  });
  it("trims surrounding whitespace", () => {
    expect(displayName(withMeta("  Alex  "))).toBe("Alex");
  });
  it("falls back to 'Account' — never the email — when unset or blank", () => {
    expect(displayName(withMeta(undefined))).toBe("Account");
    expect(displayName(withMeta(""))).toBe("Account");
    expect(displayName(withMeta("   "))).toBe("Account");
  });
});

describe("currentUsername", () => {
  it("returns the trimmed username, or '' when unset (for prefilling the form)", () => {
    expect(currentUsername(withMeta("Alex"))).toBe("Alex");
    expect(currentUsername(withMeta("  Alex  "))).toBe("Alex");
    expect(currentUsername(withMeta(undefined))).toBe("");
  });
});
