import { beforeEach, describe, expect, it } from "vitest";
import { clearUserScopedStorage, syncUserScopedStorage } from "./user-scoped-storage";

// jsdom's localStorage is broken under this runner's --localstorage-file flag,
// so install a faithful in-memory Storage (full contract: length + key(i),
// which the prefix purge iterates) on both globals for each test.
function installStorage(name: "localStorage" | "sessionStorage") {
  const map = new Map<string, string>();
  const storage: Storage = {
    get length() {
      return map.size;
    },
    key: (i: number) => Array.from(map.keys())[i] ?? null,
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => void map.set(k, String(v)),
    removeItem: (k: string) => void map.delete(k),
    clear: () => map.clear(),
  };
  Object.defineProperty(window, name, { configurable: true, value: storage });
}

function seed() {
  localStorage.setItem("mm:copilot:insights:dismissed", '["concentration:NVDA"]');
  sessionStorage.setItem("mm:copilot:ask:answer", '{"intent":"x"}');
  sessionStorage.setItem("mm:copilot:chat:floating", "[]");
  sessionStorage.setItem("mm:research:ticker", '"AAPL"');
  // non-user content that must SURVIVE
  localStorage.setItem("mm_last_seen", "123");
  localStorage.setItem("sb-e2e-auth-token", "tok");
}

beforeEach(() => {
  installStorage("localStorage");
  installStorage("sessionStorage");
});

describe("clearUserScopedStorage", () => {
  it("removes only mm:copilot:* and mm:research:* keys", () => {
    seed();
    clearUserScopedStorage();
    expect(localStorage.getItem("mm:copilot:insights:dismissed")).toBeNull();
    expect(sessionStorage.getItem("mm:copilot:ask:answer")).toBeNull();
    expect(sessionStorage.getItem("mm:copilot:chat:floating")).toBeNull();
    expect(sessionStorage.getItem("mm:research:ticker")).toBeNull();
    // analytics + auth-token untouched
    expect(localStorage.getItem("mm_last_seen")).toBe("123");
    expect(localStorage.getItem("sb-e2e-auth-token")).toBe("tok");
  });
});

describe("syncUserScopedStorage (identity change wipes the leak)", () => {
  it("first-ever identity records but does not wipe", () => {
    seed();
    expect(syncUserScopedStorage("user-A")).toBe(false);
    expect(localStorage.getItem("mm:copilot:insights:dismissed")).not.toBeNull();
  });

  it("same identity (reload / token refresh) keeps the user's own state", () => {
    syncUserScopedStorage("user-A"); // establish
    seed();
    expect(syncUserScopedStorage("user-A")).toBe(false);
    expect(sessionStorage.getItem("mm:copilot:ask:answer")).not.toBeNull();
  });

  it("a DIFFERENT account wipes the previous user's copilot/research storage", () => {
    syncUserScopedStorage("user-A"); // establish A
    seed(); // A's content
    expect(syncUserScopedStorage("user-B")).toBe(true);
    expect(localStorage.getItem("mm:copilot:insights:dismissed")).toBeNull();
    expect(sessionStorage.getItem("mm:research:ticker")).toBeNull();
    // analytics survives the account switch
    expect(localStorage.getItem("mm_last_seen")).toBe("123");
  });

  it("sign-out (→ null) after a real user wipes and forgets the identity", () => {
    syncUserScopedStorage("user-A");
    seed();
    expect(syncUserScopedStorage(null)).toBe(true);
    expect(localStorage.getItem("mm:copilot:insights:dismissed")).toBeNull();
    // a subsequent fresh sign-in is treated as first-ever (no wipe of its own state)
    seed();
    expect(syncUserScopedStorage("user-C")).toBe(false);
    expect(localStorage.getItem("mm:copilot:insights:dismissed")).not.toBeNull();
  });
});
