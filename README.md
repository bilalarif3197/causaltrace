# CausalTrace

**An AI-assisted pharmacovigilance workspace for adverse drug reaction causality assessment.**

CausalTrace helps a drug-safety reviewer reconstruct an adverse-event case, evaluate competing
etiologies, identify missing evidence, complete structured causality frameworks, and produce an
auditable conclusion — while keeping expert judgment in control.

> **AI organizes and suggests. The reviewer investigates and decides.**

> **This is a research prototype.** It does not establish medical causation, it is **not a
> medical device**, and it is **not a clinical decision tool**. Bundled demo narratives are
> synthetic and contain no patient-identifiable information.

Built for the Regeneron HackMIT 2026 prize track. MIT licensed.

---

## What this is not

Clicking a button does not return *"Drug A probably caused the event."* There is no API endpoint
that turns a narrative into a verdict, and a test asserts the old one stays deleted.

Instead, a suggestion run **populates a review workspace**. The assessment emerges from decisions
the reviewer records, in this order:

```
Case intake → AI extraction → Human review → Clinical timeline → Competing causes
  → Evidence assessment → Formal frameworks → Reviewer conclusion → Report + audit trail
```

You can move backward at any point, change evidence, and watch the downstream assessment change
with it.

---

## The guarantee that makes it a workspace

Every reviewable item carries **two parallel slots**: an immutable `AiSuggestion`, and a separate
reviewer decision. A reviewer action never writes to the AI's half, which is what keeps the audit
trail meaningful.

Downstream assessment may read **only confirmed values** — accepted or modified. An AI suggestion
nobody has looked at is a proposal, not evidence, and contributes nothing.

This is verifiable, and verified live:

```
suggest/naranjo   2.8s   Suggested answers for 10 unreviewed Naranjo item(s)

AFTER AI, BEFORE ANY REVIEW
  naranjo score : 0 (Doubtful) -- 10/10 unreviewed

AFTER REVIEWER ACCEPTS
  naranjo score : 3 (Possible)  range=[1,9]  stable=False
```

The model answered all ten items and the score stayed at zero. Without that property this is an
autonomous classifier with a confirmation dialog bolted on.

### Reviewer states

| State | Meaning |
| --- | --- |
| AI suggested | Proposed, not yet reviewed. Contributes nothing. |
| Reviewer confirmed | Accepted as-is. |
| Reviewer modified | Corrected. The original suggestion is retained beside it. |
| Reviewer rejected | Excluded. Never reaches downstream assessment or the rationale drafter. |
| Unknown | Explicitly not determinable. |
| Needs review | Verification could not confirm the cited evidence. Flagged, never deleted. |

Each state is carried by an icon, a word **and** a colour, so it survives greyscale printing and
colour-blindness.

---

## Two gates between a model assertion and the reviewer

| Gate | Question | How |
| --- | --- | --- |
| Span locator | Does this quote exist in the source at all? | Deterministic string/fuzzy alignment. No LLM, no network. |
| Verifier | Granting it exists, does it *license* this claim? | A separate LLM pass told only to falsify. |

Returns `SUPPORTED` / `PARTIALLY_SUPPORTED` / `NOT_SUPPORTED`. A failure **flags the item for
review rather than deleting it** — the reviewer decides, and the audit trail records that
something was proposed and challenged.

The verifier earns its keep on cases like this:

> **Claim:** "Viral hepatitis was excluded as an alternative cause."
> **Cited evidence:** *"Hepatitis A, B and C serologies were not obtained"*
> **Verdict:** `NOT_SUPPORTED` — the quote says the tests were *not done*, the opposite of
> exclusion. Untested is not excluded.

Clinically tempting, grammatically supported by a real quote, and wrong.

---

## Quickstart

Requirements: Python 3.11+, Node.js 20.9+.

```bash
# backend
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn main:app --reload --port 8000

# frontend, second terminal
cd frontend && npm install && npm run dev      # http://localhost:3000
```

Set `OPENAI_API_KEY` in `backend/.env` for live suggestions. Any OpenAI-compatible endpoint works
via `OPENAI_BASE_URL` — DeepSeek, Groq, OpenRouter, local Ollama. The client negotiates
structured-output support downward (strict JSON schema → `json_object` → schema-in-prompt) based
on what the provider actually rejects, and reports in the UI when output is no longer
schema-enforced. Check any configuration with `.venv/bin/python preflight.py`.

Reviewer decisions persist to SQLite, so a review survives a restart and can be resumed.

---

## Demo script

1. Open `http://localhost:3000`, load **"TMP-SMX and acute liver injury"**, click **Start case review**.
2. The case analyses itself on first open — about 20 seconds in two phases, with live progress
   and a **Skip the rest** button. Six stages read only the narrative and are fanned out
   concurrently server-side; `missing` follows after, since it reads confirmed evidence. Every item arrives marked **AI suggested**, and the Naranjo
   chip in the header still reads **0**: none of it is evidence yet. This runs once; reopening
   the case will not repeat it, and each step keeps its own button for re-running on demand.
3. Accept most, **edit** one, **reject** one. The AI's original value stays visible beside yours.
4. Anything the verifier could not confirm is flagged **Needs review** with the reason shown.
5. **Timeline** — reorder an event, change one to *Approximate*; it is labelled "timing
   uncertain" rather than given an invented date.
6. **Investigation** — four dimensions answered separately. Note rechallenge is UNKNOWN, not a
   negative: absence of a rechallenge is not evidence against causality.
7. **Competing causes** → the graph draws edges from *your* assessments; unassessed hypotheses
   stay faint. Set acetaminophen to *Weakly supported* and watch its edge change.
8. **Missing evidence** — concrete gaps with why each matters. Mark one *Unavailable*.
   Re-running this after review is better, since it then sees what you actually confirmed.
9. **Naranjo** → each item shows the AI's suggestion beside your answer. Accept all, then
   **change one answer and the score updates instantly** — pure Python, no model call.
10. **Conclusion** → choose your assessment, then draft the rationale. This is the one stage
    that never auto-runs: it writes from reviewer-confirmed evidence and fills the conclusion
    field, so letting it run before you had reviewed anything would put machine text into your
    conclusion. Edit it freely, then sign off.
11. **Report** → timeline, evidence, alternatives, gaps, frameworks, your conclusion, and the
    **AI assistance audit**: suggested vs accepted vs modified vs rejected, plus the correction rate.

Click any quoted evidence on any screen to highlight the exact sentence in the source narrative.

---

## Architecture

```
backend/
  main.py                  FastAPI. No verdict endpoint exists.
  schemas/review.py        dual-value review model; `confirmed_value` is the gate
  services/
    store.py               SQLite: cases + append-only audit
    workspace.py           all mutations; one place that audits and persists
    assessment.py          deterministic scoring + review statistics
    suggest.py             the constrained AI functions
    spans.py               quote -> character-offset resolution (no LLM)
    verifier.py            independent falsification pass
    naranjo.py             published weight table + pure-Python scorer
frontend/
  app/page.tsx             case list + intake
  app/case/[id]/page.tsx   workspace shell: step rail, source panel, active step
  components/review.tsx    status chips, accept/edit/reject, source highlighting
  components/steps/        the nine review screens
evaluation/
  evaluate_assistance.py   AI-assistance metrics (the relevant harness)
  evaluate.py              legacy verdict-accuracy comparison
  pmc_ingest.py            harvest real cases from the PMC Open Access Subset
```

**Small constrained AI functions, not one agent.** `extract_case_facts`,
`extract_timeline_events`, `classify_evidence_relationship`, `suggest_alternative_causes`,
`suggest_missing_evidence`, `verify_evidence_support`, `draft_reviewer_rationale`. Extraction is
told to be comprehensive; the verifier is told only to falsify; the rationale drafter is shown
nothing but confirmed evidence. Giving one prompt several of those jobs is what produces
confident, unfalsifiable prose.

Splitting the work also made it usable. The six narrative-only stages are computed
concurrently behind `/suggest-batch`, taking first-open analysis from 43.7s to 20.7s.

That batching is a single request by necessity, not preference: every write path loads,
mutates and saves the whole case document, so firing the per-stage endpoint six times in
parallel from the browser would let the last response win and discard the other five.
Concurrency is confined to the model calls, which do not touch the document; merging happens
on one thread in a fixed order, so the result does not depend on which call returned first.

---

## Scientific assumptions

Stated explicitly so a reviewer can disagree with them.

- **Naranjo weights** transcribed from the worksheet as published in LiverTox
  ([NBK548069](https://www.ncbi.nlm.nih.gov/books/NBK548069/)). Range −4..+13; Definite ≥9,
  Probable 5–8, Possible 1–4, Doubtful ≤0. Pinned by tests.
- **Item 6 (placebo) is UNKNOWN, not NO**, when no placebo was given. Scoring it NO adds a point
  for something that never happened.
- **Items 4/6/7/8: "not done" ≠ "done, result negative."** Answering NO asserts the challenge was
  performed and came back negative. This was a real live failure — the model answered item 4 NO
  on *"the patient was not re-exposed"*, penalising the drug for a rechallenge that never happened.
- **Item 5 requires positive exclusion** to answer NO; silence is UNKNOWN. But an affirmative
  statement ("no other medications") *is* positive exclusion.
- **No inferred dates, including years.** "3 January" with no year yields a display label and no
  ISO date. Vague wording is APPROXIMATE or RELATIVE, never EXACT.
- **No numeric causal probabilities.** The schema cannot express "83% likely".
- **Framework results are labelled "framework result", not "final decision."** The reviewer's
  conclusion is a separate, authoritative field, and the report shows when they diverge.

---

## Evaluation

```bash
backend/.venv/bin/python evaluation/evaluate_assistance.py
```

The harness measures **assistance quality**, not verdict accuracy. The claim under test is *not*
"our AI beats clinicians" — it is that structured assistance is more traceable and reviewable than
an unstructured answer.

Most of these metrics **need no gold labels**, because they are checked against the narrative
itself:

| Metric | TMP-SMX case (live DeepSeek) |
| --- | --- |
| Facts extracted | 27 |
| Quote located in source | 26 / 27 (**0.963**) |
| Verification passed | 25 · partial 0 · **failed 2** |
| Unsupported assertion rate | 0.111 |
| Naranjo traceability rate | 1.0 |

Structural comparison against a single-pass verdict:

| | assisted | single-pass |
| --- | --- | --- |
| Facts surfaced for review | 27 | 0 |
| Elements with a source span | 5 | 0 |
| Alternatives surfaced | 9 | 0 |
| Explicit UNKNOWNs | 5 | 0 |
| **Independently reviewable units** | **37** | **1** |

The baseline's zeros are structural, not a low score: a one-call verdict has no items to check, no
spans to trace, and nothing a reviewer can accept or reject piece by piece. That *is* the argument.

**Reviewer correction rate** is measured from real sessions in the database and cannot be
simulated — it needs a human to have actually disagreed. A rate near zero usually means the review
was not adversarial enough, not that the AI was perfect.

### Read this before quoting any accuracy number

Item accuracy and alternative-cause recall use **author-assigned labels on synthetic narratives**,
and the prompts were iterated against those same cases. Those are training-set numbers with no
held-out split. `evaluation/pmc_ingest.py` harvests real cases from the PMC Open Access Subset
(official NCBI APIs only, throttled and cached, never scraping) to fix this; candidates require
human confirmation before they count, and harvested article text is never committed because the
subset includes CC BY-NC-ND.

`backend/tests/test_dataset_consistency.py` asserts the dataset does not contradict itself. It was
written after the TMP-SMX reference was recorded as 5/Probable while its own item answers summed
to 3/Possible — the same error the PMC harvester flags in published papers.

---

## Testing

```bash
cd backend
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q          # 134 tests
.venv/bin/python validate_fixtures.py  # fixture quotes must be verbatim
cd ../frontend && npx tsc --noEmit && npm run build
```

The tests pin the published Naranjo weights and bands, that an unreviewed suggestion scores zero,
that `apply_review` never mutates an AI suggestion, that re-running a stage cannot clobber review
work, that bulk-accept cannot reverse an explicit decision, and that CORS accepts loopback origins
but rejects lookalikes such as `localhost.attacker.com`.

---

## Limitations

- **No real-world accuracy number exists, and the numbers that do exist are tuned** on the same
  synthetic cases. Biggest gap by a wide margin.
- **Reviewer correction rate needs real reviewers.** One simulated session is not evidence.
- **Single-drug assessment.** Naranjo applies to one suspected drug at a time; competing
  hypotheses are surfaced but not formally scored each.
- **Naranjo is a poor instrument for hepatotoxicity specifically** — not weighted for
  time-to-onset or recovery criteria, and it relies on drug levels rarely informative in
  idiosyncratic DILI. RUCAM is better there and is not implemented.
- **Global-negative items cannot be fully verified.** Each item cites one quote, but item 5
  answered NO is a claim about the whole narrative. The verifier judges item 5 against the full
  text as a workaround; the real fix is multi-quote citations.
- **The verifier is itself a model** and can over- or under-reject. The span locator is
  deterministic and the stronger of the two gates.
- **No mechanistic reasoning, no ADR database lookup, no EHR integration.** English only.
- **Single reviewer.** No authentication, no multi-reviewer comparison.

## Scope and data

Public, appropriately licensed data only. Never patient-identifiable information. Demo cases use
either drug-class labels ("Drug A, an oral antifungal agent") or long-established generics; no
investigational product is analysed as though it had a known adverse-event profile.

## License

MIT — see [LICENSE](LICENSE).
