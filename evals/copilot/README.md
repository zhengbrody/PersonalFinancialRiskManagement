# Copilot grounding eval

Makes "the LLM never invents a number" measurable and regressable. Each case
runs through the REAL router (`copilot_router.answer`) with every
evidence-source seam patched to the case's fixture; numeric claims are
extracted from the answer and tolerance-matched against the evidence packet
(`ai_eval.extract_numeric_claims` / `match_claims`, rtol 6%,
percent↔ratio + sign candidates).

## Run it

```bash
python evals/run_grounding_eval.py             # offline template mode — no key, CI-safe
python evals/run_grounding_eval.py --llm       # real LLM (needs the provider key) — the meaningful number
python evals/run_grounding_eval.py --json out.json
```

**Honest framing:** the deterministic template prints evidence verbatim, so
~100% faithfulness in template mode is a STRUCTURAL guarantee — its value is
a regression harness (router intents, evidence building, the
extraction/matching machinery) and the measurement frame. Only `--llm`
produces a meaningful faithfulness number. The metric is numeric
TRACEABILITY, not semantic correctness: an answer citing an evidence number
for the wrong metric still matches (known limit, documented in
`induced-07`).

## cases.jsonl — 30 cases

| category | n | what it covers |
|---|---|---|
| `normal` | 14 | ordinary questions across intents — every figure must trace to evidence |
| `induced` | 8 | traps that ASK for numbers structurally absent from the evidence (forecasts, price target with a null analyst block, historical values, empty book, CPI not in the macro packet, 99.9% VaR, third-party data, bp fee with a number-free scan) — inventing any figure is a violation; refusing / stating the gap passes |
| `boundary` | 8 | numbers that exist and must be cited RIGHT: negative drawdown sign, $ thousands separators, percent↔ratio, 1.35× multiples, 720/1000 compound, rounding within rtol, confidence level living in the label, CJK prose |

One JSON object per line:

```json
{"id": "…", "category": "normal|induced|boundary", "intent_expected": "…",
 "question": "…", "trap": "(induced only) what the trap is",
 "fixture": {"score": {"overall_score": 720, "metrics": {…}} | null,
              "factpacks": {"TICKER": {…}}, "macro": {…}, "scans": {…}}}
```

Adding a case: pick the category, author the fixture, and check the intent —
`classify()` keywords decide routing (`"what is …"` → explain_metric, a lone
ticker → ticker_research, …); the runner hard-fails on intent mismatches in
template mode, so a mis-routed case is caught immediately.

## CI

`backend-tests` already enforces the offline suite via
`backend/tests/test_ai_eval_grounding.py` (full 30-case template run must be
100% traceable). The dedicated non-blocking job below additionally surfaces
it as its own check — it lives in `.github/workflows/ci.yml`, which needs a
`workflow`-scoped token to push (same constraint as ml-health/weekly-digest;
snippet kept here so it's recoverable from the repo):

```yaml
  copilot-eval:
    runs-on: ubuntu-latest
    continue-on-error: true # advisory (mypy precedent) — backend-tests is the hard gate
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - name: Install backend deps
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install -r backend/requirements-backend.txt
      - name: Grounding eval (offline template mode)
        run: python evals/run_grounding_eval.py --threshold 0.98
```
