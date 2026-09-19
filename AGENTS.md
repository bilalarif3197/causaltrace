# CausalTrace — agent notes

Regeneron HackMIT 2026 prize track. See `README.md` for the full picture; this file is the
short version of how to work in the repo without breaking anything.

## Run

```bash
# backend (http://localhost:8000)
cd backend && .venv/bin/uvicorn main:app --reload --port 8000

# frontend (http://localhost:3000)
cd frontend && npm run dev
```

No `OPENAI_API_KEY` → mock mode: the full pipeline runs against `backend/fixtures/`, but only
the three built-in cases work. A custom narrative returns 422 by design, not by accident.

## Verify (run all four before calling anything done)

```bash
cd backend && .venv/bin/python -m pytest -q          # 134 tests
cd backend && .venv/bin/python validate_fixtures.py  # 136 quotes must be verbatim
cd frontend && npx tsc --noEmit && npm run build
backend/.venv/bin/python evaluation/evaluate_assistance.py
```

Cases persist to `backend/causaltrace.db` (SQLite, gitignored). Tests use a temp DB via
`tests/conftest.py`.

Python venv lives at `backend/.venv` (Python 3.13). Frontend is Next.js 16 + React 19 +
Tailwind 4 + `@xyflow/react`, all pinned exactly.

## The product invariant

**AI organizes and suggests. The reviewer investigates and decides.** There must be no
endpoint or UI path that turns a narrative straight into a causality verdict.

Every reviewable entity holds an immutable `AiSuggestion` beside a separate reviewer slot.
`confirmed_value` returns None unless a human accepted or modified it, and downstream
assessment may read nothing else. A reviewer action must never write to `ai`. If an
unreviewed suggestion can move a score, the product has regressed into an autonomous
classifier with a confirmation dialog.

Re-running a suggestion stage must keep reviewed items, refresh only the AI half of
untouched ones, and add new candidates. Bulk actions touch pending items only.

## Other invariants — do not break these

1. **The LLM never computes the Naranjo total.** It answers items; `naranjo.score_items()`
   sums them in pure Python from the published weight table. Keep those halves separate.
2. **Naranjo weights are pinned by tests** against the published worksheet (range −4..+13).
   If a weight test fails, the table is wrong, not the test.
3. **Two grounding gates.** `spans.locate_span` rejects quotes absent from the source
   (deterministic); `verifier.verify` rejects real quotes that do not license their claim
   (separate LLM pass). A claim failing either becomes UNKNOWN. Never let an ungrounded
   answer carry a non-zero score.
4. **Rejected claims stay visible.** Demote to UNKNOWN with a reason; never silently delete.
5. **Never invent data to fill a field** — no inferred dates, and no inferred *years* (the
   demo narratives say "3 January" with no year, so `date` stays null and only
   `display_date` is set). No numeric causal probabilities anywhere.
6. **Absence of evidence ≠ evidence of absence.** Naranjo item 5 is NO only on positive
   exclusion; item 6 is UNKNOWN when no placebo was given.
7. **Provider code stays in `services/llm_client.py`.** No service module imports a vendor SDK.
8. **Evidence valence needs icon + text label + colour**, never colour alone.

## Editing fixtures

`backend/fixtures/<case_id>/<stage>.json` replays stage-level model output. Every
`evidence_text` must be a character-for-character substring of that case's narrative in
`backend/services/cases.py`. Run `validate_fixtures.py` after any edit — it catches retyped
quotes that would silently degrade to fuzzy matching.

Claim ids are positional (`c000`, `c001`, …) over the full `extraction.json` list including
UNKNOWN entries, and `verification.json` must reference those exact ids. Inserting a claim
mid-list renumbers everything after it.

## Honesty constraints (these are product requirements, not style)

- Mock-mode evaluation numbers are circular: the fixtures and `evaluation/cases.json`
  references share an author. The harness prints this on every run. Do not remove that
  banner, and do not quote mock numbers as accuracy.
- Never describe the system as establishing causation, diagnosing, or replacing a clinician.
- Demo cases use drug-class labels ("Drug A, an oral antifungal agent"), never product names.

## Harvesting real cases (evaluation/pmc_ingest.py)

Official NCBI interfaces only: E-utilities, the PMC ID converter, efetch, the BioC API.
Never scrape the PMC website — it is prohibited and gets the IP blocked. Requests are
throttled with backoff and cached under `evaluation/.pmc_cache/` (gitignored).

Three rules that must not be relaxed:

1. **Auto-parsed scores are candidates, not references.** Records carry `needs_review:
   true` plus the sentence the value came from. `--append` refuses unreviewed records.
2. **Never commit harvested article text.** The OA subset includes CC BY-NC-ND. Narratives
   live in the gitignored cache; `cases.json` holds a PMCID pointer unless the licence
   clearly permits redistribution. `evaluate.py` resolves narratives from that cache.
3. **Published references can be wrong.** Score/band disagreements (e.g. "score 4 ...
   probable", where 4 is Possible) are flagged via `internal_inconsistency`.

`truststore` is required: NCBI's cross-signed chain fails certifi validation but passes
against the OS trust store.
