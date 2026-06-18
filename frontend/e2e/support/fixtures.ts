/**
 * Shared E2E test object. An auto fixture installs the mocked backend on every
 * test's page, so specs only worry about behavior. Auth is opt-in per test via
 * `seedSession(page)` (so the same setup covers signed-in AND anonymous flows).
 */

import { test as base, expect } from "@playwright/test";
import { mockBackend } from "./mock-api";

export const test = base.extend<{ mockApi: void }>({
  mockApi: [
    async ({ page }, use) => {
      await mockBackend(page);
      await use();
    },
    { auto: true },
  ],
});

export { expect };
