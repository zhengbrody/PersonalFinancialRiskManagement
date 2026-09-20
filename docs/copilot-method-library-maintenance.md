# Reviewed method library maintenance

This is a small editorial library, not a model fine-tuning corpus or a crawler.
The four existing primary-source summaries retain their 2026-09-11 review date;
this change does not claim a new source review. Their next review is due
2027-03-10 (UTC, exclusive). The interval is an internal maintenance policy,
not a statement about how quickly investment knowledge changes.

## Publication and withdrawal

`backend/app/services/analyst_methods.py` keeps the paraphrases (`CARDS`), explicit
approval records (`REVIEWS`), and approved content fingerprints (`APPROVED_CONTENT`).
New answers only receive a card if the version, source URL, review date and whole
serialized content match approval and today's UTC date is inside the review
window. Missing approval and future reviews fail closed. No scheduled network
retrieval is performed. An unavailable method removes its dependent research
questions, but does not suppress independently verified numerical research.

To review a card:

1. Read the original author/institution source using permitted access. Record the
   reviewer, actual UTC review date, source URL and supported claims in the PR.
2. Check applicability, limitations, counterpoint and falsification checks. Keep
   paraphrases short; do not copy articles or add claims unsupported by the source.
3. Change the card version, actual review date and approval record. Set a finite
   next-review date. Refresh that card's SHA-256 of `card.model_dump_json().encode()`
   after editorial review. Never regenerate all approvals automatically on startup.
4. Run lifecycle, research, and answer-boundary tests below and review the diff.

To withdraw a method, set its `MethodReview.status` to `withdrawn` and record a
specific reason. Keep its ID/version for auditing; do not replace history with a
new interpretation. Deploying the library change makes subsequent answers stop
using it. Previously captured answers remain dated historical evidence; this
library does not rewrite signed plans or claim to revoke already displayed text.
Renewal requires an actual source review, not extending a date to silence a test.

## Offline acceptance matrix

Run with synthetic provider fixtures and no model/data credentials:

```sh
/opt/anaconda3/bin/python -m pytest backend/tests/test_analyst_method_lifecycle.py backend/tests/test_copilot_research.py backend/tests/test_decision_support.py -q -o addopts=
```

The suite verifies current methods remain usable (including answerable English
and Chinese concept questions), invalid approvals remove dependent hypotheses,
wrong-security and stale/undated/nonfinite numbers never become evidence, source
failures remain explicit, ticker comparisons reach research, and provider
instructions never enter the model prompt or numerical evidence. Candidate
requests with missing account constraints clarify rather than fabricate trades.
Research metadata cannot authorize execution, rank account candidates, or save a
plan. These are deterministic regression checks, not a measured live-model
accuracy benchmark. New production-model evaluations need a versioned model,
prompt, labelled questions and reproducible scoring before any training decision.

No new data provider, paid API, model training, or automatic continuous monitoring
is introduced by this maintenance mechanism.
