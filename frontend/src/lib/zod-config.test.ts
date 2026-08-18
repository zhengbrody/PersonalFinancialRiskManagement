/**
 * The JIT compiler must stay off: under the enforcing CSP (no 'unsafe-eval')
 * Zod's `new Function` probe is rejected, and the browser reports the
 * violation even though Zod swallows the throw — that was 417 reports/month.
 */

import { describe, expect, it } from "vitest";
import { z } from "zod";
import "./zod-config";

describe("zod global config", () => {
  it("disables the JIT validator compiler", () => {
    expect(z.config().jitless).toBe(true);
  });

  it("still validates correctly on the interpreted path", () => {
    const schema = z.object({ n: z.number(), s: z.string().optional() });
    expect(schema.parse({ n: 1 })).toEqual({ n: 1 });
    expect(schema.safeParse({ n: "no" }).success).toBe(false);
  });
});
