/**
 * Vitest setup — runs once before each test file.
 *
 * Pulls in jest-dom's custom matchers (`toBeInTheDocument` etc.) and
 * makes sure tests don't accidentally hit the real network: every
 * `fetch` call must be mocked in the test itself.
 */

import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  // Clear persisted state (useSessionState) so a ticker/conversation saved by
  // one test doesn't hydrate into the next and change what renders.
  try {
    sessionStorage.clear();
    localStorage.clear();
  } catch {
    /* storage may be stubbed/unavailable in a given test */
  }
});
