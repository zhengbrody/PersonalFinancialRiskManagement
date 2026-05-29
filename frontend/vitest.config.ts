import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

/**
 * Vitest config — jsdom for component tests, the `@/*` path alias
 * matches `tsconfig.json` so `import { apiFetch } from "@/lib/api"`
 * resolves identically in source and tests.
 */
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.test.{ts,tsx}", "src/lib/api-types.ts"],
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
