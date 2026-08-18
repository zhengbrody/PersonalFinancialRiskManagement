/**
 * Global Zod configuration — imported for its side effect, and it must run
 * BEFORE the first schema parse (ES imports are evaluated depth-first, so a
 * top-of-file import of this module in each early parser is sufficient).
 *
 * `jitless` turns off Zod v4's JIT validator compiler, which builds validators
 * with `new Function(...)`. Two reasons, and neither is a preference:
 *
 *  1. Our Content-Security-Policy has no `'unsafe-eval'`, so under the
 *     enforcing policy the JIT path is unavailable anyway — Zod probes
 *     `new Function("")`, catches the CSP rejection and falls back to the
 *     interpreted path. Setting `jitless` makes that the behaviour in BOTH
 *     modes, so validation can't differ between Report-Only and enforcing.
 *  2. The probe itself fires a `securitypolicyviolation` even though the throw
 *     is swallowed (Zod's own source says so at `v4/core/util.js`). That was
 *     417 violation reports/month in Sentry — noise that would have masked a
 *     real CSP gap.
 *
 * The alternative — adding `'unsafe-eval'` to `script-src` — was rejected: it
 * re-permits the exact injection class the policy exists to stop, to speed up
 * response validation that is not on a hot path.
 */

import { z } from "zod";

z.config({ jitless: true });
