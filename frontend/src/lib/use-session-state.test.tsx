/**
 * useSessionState — the load-bearing key-change reset: switching to a NEW
 * partition with no stored value must reset to `initial` (not keep the previous
 * partition's value). This is what isolates per-portfolio Copilot answers.
 */

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { useSessionState } from "./use-session-state";

function installSessionStorage() {
  const map = new Map<string, string>();
  const storage: Storage = {
    get length() {
      return map.size;
    },
    key: (i) => [...map.keys()][i] ?? null,
    getItem: (k) => map.get(k) ?? null,
    setItem: (k, v) => void map.set(k, String(v)),
    removeItem: (k) => void map.delete(k),
    clear: () => map.clear(),
  };
  Object.defineProperty(window, "sessionStorage", { configurable: true, value: storage });
  return map;
}

let store: Map<string, string>;
beforeEach(() => {
  store = installSessionStorage();
});
afterEach(() => store.clear());

function Probe({ storeKey }: { storeKey: string }) {
  const [value, setValue] = useSessionState<string>(storeKey, "INITIAL");
  return (
    <div>
      <span data-testid="v">{value}</span>
      <button onClick={() => setValue("SET")}>set</button>
    </div>
  );
}

describe("useSessionState key change", () => {
  it("resets to initial when the new key has no stored value", () => {
    const { rerender } = render(<Probe storeKey="k:A" />);
    // write a value under k:A
    screen.getByText("set").click();
    // switch to an empty partition k:B → must reset to INITIAL, not keep "SET"
    rerender(<Probe storeKey="k:B" />);
    expect(screen.getByTestId("v").textContent).toBe("INITIAL");
  });

  it("restores the partition's own stored value on switch back", () => {
    store.set("k:A", JSON.stringify("A-VALUE"));
    const { rerender } = render(<Probe storeKey="k:B" />);
    expect(screen.getByTestId("v").textContent).toBe("INITIAL"); // empty B
    rerender(<Probe storeKey="k:A" />);
    expect(screen.getByTestId("v").textContent).toBe("A-VALUE"); // restored A
  });
});
