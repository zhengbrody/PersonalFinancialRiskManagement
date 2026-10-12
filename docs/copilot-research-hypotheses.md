# Copilot research hypotheses (D slice, local, default-off)

Status: local implementation on `codex/d-research-hypotheses`. Behind the existing
`MINDMARKET_DECISION_SUPPORT_ENABLED` flag (default off). No migration, no new
provider, no external retrieval, no model training, no deployment.

## 1. What a hypothesis is

A `ResearchHypothesis` turns a research view into something that can be checked.
It rides inside the existing `CopilotResearch` context of a Copilot answer
(`research_context[].hypotheses`, additive). Two origins exist today:

| origin | claim basis | example |
| --- | --- | --- |
| `user_view` | `user_assumption` | "I think NVDA net margin is above 50%" |
| `method_question` | `model_inference` | MindMarket's valuation/downside questions built from reviewed method cards |

A claim attributed by the user to someone else ("according to an analyst …") stays a
`user_view`: the cited source was not retrieved, so it is recorded as missing with
reason `cited_source_not_retrieved`. No hypothesis is generated from a news title:
article bodies are not retrieved, so a headline is never treated as a claim the
article supports.

Each hypothesis carries: claim, subject ticker + scope, `as_of`, source references
(id, type, author, publisher, URL, publication date, retrieval date, usage basis,
quote locator or paraphrase flag, verification level), counter-arguments,
explicit invalidation conditions, status, and three strictly separated lists:

* **research evidence** — `evidence_observation_ids`: only ids of dated FactPack
  `ResearchObservation`s in the same context (provider values with block-level
  provenance). A method-card id can never appear here (schema validator).
* **model inference** — `inference`: text the system derived (method questions,
  generic checks). Never numeric evidence and never sent to the LLM.
* **user assumption** — the claim itself and any threshold in a `test`.

## 2. Status: the only deterministic judgement

Status is computed, never phrased by a model, and is re-verified by the
`CopilotResearch` validator (an injected or mislabelled status fails validation).

Definition. A hypothesis may carry a `test = (observation_id, comparator,
threshold)` parsed from the user's own words (narrow EN/ZH grammar: metric alias,
comparator, number). Let `o` be the referenced observation.

* `o.status == "available"` and `value ⋈ threshold` holds → `supported_by_evidence`
* `o.status == "available"` and it fails → `contradicted`
* `o.status == "stale"` → `stale`
* otherwise (missing / undated / no test) → `unverified`

Method-question hypotheses carry no test: `stale` if any linked observation is
stale, else `unverified`. They are never `supported_by_evidence`/`contradicted`.

`⋈ ∈ {>, ≥, <, ≤}`. Fractions compare in fraction units (a user "50%" is 0.50).
Valuation time: the FactPack provider snapshot timestamp at `captured_at`.
Invariant: `supported_by_evidence` only means the latest provider snapshot
satisfies the user's stated threshold — it does not establish the thesis, a
reporting period or suitability. Method cards are never a number source: a test
can only reference an observation id, and a missing observation stays
`unverified` with `observation_missing` regardless of active method cards.

Missing items are typed (`no_authorized_source`, `reporting_period_unavailable`,
`observation_missing`, `observation_stale`, `observation_undated`,
`no_testable_predicate`, `cited_source_not_retrieved`). Every hypothesis records
`no_authorized_source` (no licensed document retrieval exists) and, when it links
observations, `reporting_period_unavailable` (FactPack has no period).

## 3. Carrying a hypothesis into the account comparison

The existing `POST /copilot/compare-change` accepts an optional, additive
`hypothesis` assumption. The hypothesis text never travels: only

* `hypothesis_id` (bounded pattern), `subject` (ticker),
* `price_change_pct` — a number the user typed (−95 … +100, non-zero),
* `basis: "user_assumption"`, `user_confirmed: true` (StrictBool literal).

The frontend sends it only after the user enters the price change and ticks the
confirmation. Without `user_confirmed=true` the request is rejected (422). The
assumption authorizes nothing: it adds one deterministic row to the existing
comparison and is replayed/saved with it.

### Math (closed form)

Inputs from the comparison's single capture: subject value `V = q_T · close_T`
(Decimal, captured close), reduction amount `A`, user price change `p = pct/100`,
net equity `E` (unchanged by the reduction, already asserted by cash conservation).

```
V_base = V
V_cand = V − A        if subject == reduction ticker, else V
baseline_pnl  = V_base · p
candidate_pnl = V_cand · p
baseline_equity  = E + baseline_pnl
candidate_equity = E + candidate_pnl
invariant: candidate_pnl − baseline_pnl = −A·p (same ticker) or 0
```

Isolated single-name price move at the captured close; every other holding, cash,
margin and option leg is unchanged. No probability is attached.

`not_computable` (numbers null, typed reason) when:
* `subject_not_held` — no captured stock/ETF position in the subject;
* `subject_has_options` — any option leg on the subject (a stock-only shock would
  misstate option exposure; options are not repriced here).

The comparison itself still completes in those cases.

## 4. Injection and untrusted text

User and provider text are data: they are truncated, stripped of control
characters, never placed in the LLM prompt by this feature, cannot set status,
cannot call tools and cannot populate the comparison request. The grounding eval
adds EN/ZH cases where provider headlines carry fake numbers/instructions and a
scripted model narrative cites a method card as a number source; both fail closed.

## 5. Method-card maintenance gate

`analyst_methods.REVERIFICATIONS` records actual source re-verifications
(reviewer, date, URLs checked, note). A test enforces: a card's review date equals
the 2026-09-11 baseline or the latest recorded re-verification date; any
re-verification lists a reviewer and the approved source URL; and `review_due` is
exactly `reviewed_at + 180 days`. Moving a due date or review date without a
recorded re-verification fails. This slice re-verified no source, so no dates moved.

## 6. Limits

No licensed document retrieval, no filing/period provenance, no claim-level
citation of external articles, no automatic thesis tracking. A `user_view` without
a parseable metric/threshold remains `unverified` (`no_testable_predicate`).

## 7. Related fix

`copilot_router.classify` sent any message containing "margin" to `margin_risk`, so
a view about NET/operating margin never reached research. Profitability-margin
phrases are now stripped before the margin-loan cue; "Am I using too much margin?"
still routes to `margin_risk` (tested both ways).
