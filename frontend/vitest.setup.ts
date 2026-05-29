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
});
