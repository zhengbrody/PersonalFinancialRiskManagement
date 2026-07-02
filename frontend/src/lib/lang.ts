/**
 * Deterministic CJK detection — mirrors the backend rule in
 * `libs/ai_agents/portfolio_agents.py:detect_reply_language`:
 * at least 2 CJK ideographs ("一".."鿿") that make up ≥20% of the
 * non-space characters, so a stray character in an otherwise-English
 * message doesn't flip the UI language.
 */
export function hasCjk(text: string): boolean {
  if (!text) return false;
  let cjk = 0;
  let dense = 0;
  for (const ch of text) {
    if (/\s/.test(ch)) continue;
    dense += 1;
    if (ch >= "一" && ch <= "鿿") cjk += 1;
  }
  return cjk >= 2 && dense > 0 && cjk / dense >= 0.2;
}
