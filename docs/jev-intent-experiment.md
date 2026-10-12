# Jev intent-routing experiment

Status (2026-10-10): **adapter implemented, real effectiveness UNVERIFIED (no key).**
Default OFF. Not wired into the live `/ask` path. Nothing here changes routing,
arithmetic, authorization, signing, saving or orders.

## 1. Vendor facts — verified vs unverified

All sources fetched **2026-10-10**. "Verified" means read on a TypeSafe-owned
page (typesafe.ai / docs.typesafe.ai) or the official package registry entry.
Nothing was verified by calling the API: there is no key on this machine and no
account was created.

| Fact | Status | Value | Source |
|---|---|---|---|
| Endpoint | verified (docs) | `POST https://api.typesafe.ai/v1/systemone` | https://docs.typesafe.ai/api.md , https://docs.typesafe.ai/introduction/quickstart.md |
| Auth | verified (docs) | `Authorization: Bearer <API_KEY>`; key from https://console.typesafe.ai/keys ; SDK env var `TYPESAFE_API_KEY` | quickstart; https://docs.typesafe.ai/sdk/python/api/constants.md |
| Request schema | verified (docs) | `{state: string\|object\|array, model: string, questions: map<id, Question>}`; Question `type` ∈ `noul`/`choice`/`score`, each with `instructions`; Choice `criteria` = map option→description, **max 255 options** | api.md |
| Choice response | verified (docs) | `answers[id] = {type:"choice", choice, probabilities{option:p}, confidence}`; top level also `model` (versioned id) and `usage{input_tokens, output_tokens}` | api.md |
| Errors | verified (docs) | 401 bad key · 422 validation · 429 rate limit · 529 overloaded (retry with backoff) | api.md |
| Model ids / pinning | verified (docs) | current `jev-1.13.0`; aliases `jev-latest` and `jev-preview` both → `jev-1.13.0`; aliases move on release; docs advise pinning the versioned id when thresholds were tuned | https://docs.typesafe.ai/models.md |
| Pricing | verified (docs) | $0.042 / Mtok input ($42 / Btok); output tokens free | models.md; https://typesafe.ai (homepage) |
| Rate limits | verified (docs), **explicitly unstable** | 100K tok/s, 80 req/s per account; "can change without notice" | models.md |
| Context | verified (docs) | 64k tokens per request; 32k for state + longest question; text only | models.md |
| Language | verified (docs) | "English is the primary training language… CJK scripts are handled but not equally well; test on your own content" | models.md |
| Training on data | verified (policy) | Privacy Policy (last updated Nov 19 2025): "We will not train or fine tune any … models on your prompts or other Input"; models.md: "Jev is not trained on customer requests or responses" | https://typesafe.ai/legal/privacy-policy , models.md |
| Retention | verified (policy) — **no specific period** | Privacy Policy: retained "as long as reasonably necessary…"; DPA (last updated Apr 24 2026): "as long as necessary taking into account the purpose"; ZDR only for enterprise customers | privacy-policy; https://typesafe.ai/legal/data-processing ; https://docs.typesafe.ai/legal.md |
| Region | verified (policy) | "The Services are hosted in the United States." No region selection documented. Subprocessor list at https://trust.typesafe.ai/subprocessors (not fetched) | privacy-policy; DPA |
| Python SDK | verified (registry) | PyPI `typesafe-sdk` 0.7.4; repo github.com/typesafe-ai/typesafe-sdk-python; SDK default timeout 10 s (we do NOT use the SDK — plain `httpx`, no new dependency) | https://pypi.org/pypi/typesafe-sdk/json ; constants.md |
| Availability | verified (homepage) | "Early access available" | https://typesafe.ai |
| OpenRouter listing | verified on OpenRouter's own page only | `typesafe/jev-1.13` listed; price/data policy not shown there | https://openrouter.ai/provider/typesafe |
| Vercel AI Gateway availability | **unverified** | second-hand only | — |
| "Waitlist" mechanics, account approval time | **unverified** | second-hand only | — |
| Latency claims ("40–200× faster", "<100 ms") | **unverified** (vendor marketing; not measured by us) | homepage example 0.114 s | https://typesafe.ai |
| "Zero hallucinations" / calibration quality | **unverified** (vendor claim; schema-constrained output is verifiable, calibration on our data is not) | — | https://typesafe.ai |

Second-hand articles (datacamp, eesel, towardsai, orcarouter, horadecodar) were
used only to find the official pages, never as a source of record.

## 2. Adapter — `backend/app/services/jev_intent.py`

* One Choice question over the router's **closed** 10-label set
  (`copilot_router._KW` keys; a test pins equality). Labels outside the set,
  wrong answer type, missing/NaN/out-of-range/boolean confidence → `None`.
* `state` = the user's question text only, stripped, ≤500 chars. No holdings,
  account data, page route, prompts or user id. (Anything the *user typed* —
  e.g. a ticker or a dollar figure — is part of the question and is sent.)
* Model pinned to `jev-1.13.0` (not the moving alias).
* Timeout 1.5 s; per-process budget 30 calls/min and 600 calls/h; never raises.
* Config: `MINDMARKET_JEV_INTENT_ENABLED` (default false) and `TYPESAFE_API_KEY`,
  read only in `backend/app/core/config.py` (key is `repr=False`), forwarded in
  `compose.split.yml` with blank/false defaults (the deploy-config guard requires
  every config-read variable to be forwarded).
* `shadow_compare(question)` returns `{current, jev, agree, jev_confidence,
  jev_model, latency_ms}` and logs only the label enums, agreement and latency —
  never text. **The deterministic label stays authoritative**; nothing calls this
  from `/ask` yet.

Note: `decision_support.classify_task` is a separate, regex-based gate that
decides explanation/clarification/candidate tasks *before* evidence; it is out of
scope for Jev and must stay deterministic (it governs what is computed and shown,
including candidate-request handling).

## 3. Eval set — `evals/intent/cases.jsonl`

148 questions (78 EN, 70 ZH incl. a few code-switched), **59 marked ambiguous**.
Every gold label was written by the research engineer acting as the human
labeller. **Treat them as provisional pending owner review.**

Labelling rules (applied consistently):

1. Pure definition with no personal reference → `explain_metric`. A personal
   metric *value* ("what's my beta") → the domain intent (here `portfolio_diagnosis`).
2. A conditional/hypothetical effect on the user's own book ("if rates rise, what
   happens to my portfolio") → `scenario_simulation`; current status of the market
   or economy → `macro_rates`.
3. A question whose explicit ask is "what should I do / how do I reduce" →
   `action_plan`, even if it also states a diagnosis.
4. Own options positions → `options_risk` even when a ticker is present; margin /
   leverage as the asked-about mechanism → `margin_risk`.
5. Two or more named securities compared (codes or Chinese company names) →
   `compare_tickers`; one named security → `ticker_research`.
6. No intent ("hi", "你好") → `portfolio_diagnosis` (the router's default).

**Selection bias, stated plainly:** the ambiguous subset was written with
knowledge of the current classifier's keyword traps (e.g. "recession", "bear
market", "fall", `CVAR` read as a ticker, Chinese company names without codes).
These numbers measure behaviour on hard cases; they are **not** an estimate of
production accuracy on real traffic.

## 4. Current-classifier results (offline, 2026-10-10)

`python evals/intent/run_intent_eval.py`

| Subset | n | correct | accuracy |
|---|---|---|---|
| overall | 148 | 103 | 0.696 |
| clear | 89 | 79 | 0.888 |
| **ambiguous** | 59 | 24 | **0.407** |
| English | 78 | 59 | 0.756 |
| Chinese | 70 | 44 | 0.629 |
| ambiguous EN / ZH | 29 / 30 | 12 / 12 | 0.414 / 0.400 |

Dominant ambiguous-subset errors: `macro_rates` gold sent to
`scenario_simulation`/`portfolio_diagnosis` (keyword traps and missing market
words); `scenario_simulation` gold sent to `macro_rates` (any rate cue wins over a
personal hypothetical); Chinese company names never extracted as tickers
(→ `portfolio_diagnosis`); "explain my X" forced to `explain_metric`. Clear-case
misses are vocabulary gaps (`手续费`, `交税`, `强平`, `下一步`, `CVAR`-as-ticker).
`portfolio_diagnosis` has high recall (0.96) but low precision (0.54) because it
is the fallback bucket.

Jev column: **not run — no key**.

## 5. Calibration design (for when a key exists)

* Jev's `confidence` is an input to the analysis, **not** a threshold by fiat.
  Vendor docs themselves say thresholds depend on domain and must be tested.
* `run_intent_eval.py --jev` records Jev's label and confidence per case, prints a
  5-bin reliability table (confidence bin → observed accuracy against gold), and
  chooses the **lowest cut-off whose accepted subset has a Wilson 95% lower bound
  on accuracy ≥ `--target-precision`** (default 0.90). If none qualifies, no
  threshold is adopted.
* It then reports a hybrid policy (Jev above the eval-derived cut-off, the
  deterministic label otherwise) so the comparison is against the actual
  decision rule, not raw Jev accuracy.
* With 148 cases the Wilson bound is wide; a threshold from this set is a starting
  point only. Before any routing change: owner-reviewed gold labels, a held-out
  split (choose the cut-off on one half, report on the other), and a shadow log
  window of real traffic (label enums only) to measure disagreement rate.
* Any threshold is tied to the pinned `jev-1.13.0`; a version change requires a
  re-run.

## 6. What the owner must provide to run the real comparison

1. Accept TypeSafe's Master Customer Agreement / Terms and Privacy Policy
   (https://typesafe.ai/legal/mca , /legal/privacy-policy , DPA
   /legal/data-processing) — a business decision: question text would leave our
   infrastructure to a US-hosted processor with non-specific retention (ZDR is
   enterprise-only). Privacy Policy subprocessor disclosure for MindMarket would
   need a TypeSafe line before any production shadow traffic.
2. An API key from https://console.typesafe.ai/keys (early access), exported as
   `TYPESAFE_API_KEY` in the shell running the eval — never pasted into chat or
   committed. Cost of one full eval run ≈ 148 × ~700 input tokens ≈ 0.1 Mtok ≈
   **$0.005** at the published price (estimate; output tokens free).
3. Owner review of the 148 gold labels (or a second labeller) before results are
   trusted.

Then: `TYPESAFE_API_KEY=… python evals/intent/run_intent_eval.py --jev --json out.json`.
