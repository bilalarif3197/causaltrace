# CausalTrace

**Evidence-grounded causality assessment for adverse drug event case narratives.**

CausalTrace reads a published adverse-drug-event case narrative and produces a structured,
auditable causality assessment: a reconstructed timeline, the competing explanations the
narrative actually supports, formal Naranjo and WHO-UMC assessments, and an explicit account
of what could not be determined. Every factual claim traces back to an exact span of the
source text.

> **This is a research prototype.** It does not establish medical causation, it is **not a
> medical device**, and it is **not a clinical decision tool**. It is intended to support
> human assessors, not replace them. The bundled example narratives are synthetic and contain
> no patient-identifiable information.

Built for the Regeneron HackMIT 2026 prize track ("Did the Drug Cause It? Automating
Causality Assessment"). MIT licensed.

---

## The problem

A temporal relationship is not causality. Consider:

> Drug A starts. Drug B starts five days later. Two weeks after that the patient develops
> liver injury. An infection is also documented. Drug A is stopped, Drug B continues, and
> liver markers later improve.

At least five explanations survive that narrative: Drug A, Drug B, the infection, an
interaction, or insufficient evidence. A system that returns "probable — Drug A" has not
assessed the case; it has discarded most of it.

Two failure modes matter more than raw accuracy here:

- **Confident wrongness.** General-purpose models produce fluent causality verdicts that
  diverge from expert assessment. Fluency is not evidence.
- **Missing data is the normal case.** In real pharmacovigilance practice, 4 of the 10 Naranjo
  items are answered "unknown" over 85% of the time — rechallenge, placebo, drug levels, and
  dose-response — and they are among the most heavily weighted. A system that only works on
  complete cases solves nothing.

CausalTrace is built around making both of those visible rather than papering over them.

---

## What makes this different from asking a model for a score

**1. The model never computes the score.** It answers each of the 10 Naranjo items
independently with YES / NO / UNKNOWN plus a supporting quote. The total is then summed in
plain Python from the published weight table. A language model cannot mis-add a worksheet it
never adds. (Our evaluation catches exactly this in the single-pass baseline, which
self-reported a total of 4 where its own item answers summed to 2.)

**2. Two independent gates stand between a model assertion and the user.**

| Gate | Question | How |
| --- | --- | --- |
| Span locator | Does this quote exist in the source at all? | Deterministic string/fuzzy alignment, no LLM, no network |
| Verifier | Granting it exists, does it *license* this claim? | A separate LLM pass told only to falsify |

A claim failing either gate is converted to UNKNOWN, not silently deleted — the audit trail
records that something was proposed and rejected. An ungrounded Naranjo answer is forced to
UNKNOWN, so it scores 0 and cannot move the total by any path.

The verifier earns its keep on cases like this one, from the bundled demo:

> **Claim:** "Viral hepatitis was excluded as an alternative cause."
> **Cited evidence:** *"Hepatitis A, B and C serologies were not obtained"*
> **Verdict:** `NOT_SUPPORTED` — the quote says the tests were *not done*, which is the
> opposite of exclusion. Untested is not excluded.

That claim is clinically tempting, grammatically supported by a real quote, and wrong. It is
the kind of error that inflates a causality score in the dangerous direction.

**3. Uncertainty is quantified, not hedged.** Because every UNKNOWN item has a known possible
weight range, we report the interval the total *could* occupy if the unknowns were resolved.
On the ambiguous demo case the score is 3 ("Possible") but the interval is **[1, 9]** — which
spans three classification bands. The UI says the classification is unstable, because it is.

**4. Competing hypotheses are first-class.** Each candidate cause gets its own
supports / argues-against / not-reported buckets, and the system is comfortable concluding
that the evidence cannot distinguish two of them. Strength is a qualitative label; the schema
literally cannot express "83% likely", because that number does not exist in this evidence.

**5. Absence of evidence is never evidence of absence.** Naranjo item 5 (alternative causes)
is answered NO only when the narrative *positively excludes* alternatives. Silence is
UNKNOWN. This matters: flipping item 5 from YES to NO swings the total by 3 points and can
move the band on its own — it is the single most consequential judgement in the scale, and
the easiest to get wrong by default.

---

## Quickstart

Requirements: Python 3.11+, Node.js 20.9+.

**Backend**

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn main:app --reload --port 8000
```

**Frontend** (in a second terminal)

```bash
cd frontend
npm install
npm run dev          # http://localhost:3000
```

### Mock mode vs live mode

With **no API key**, CausalTrace runs in **mock mode** and is fully demonstrable. This is not
a canned screenshot: the mock client replays *stage-level model output* from
`backend/fixtures/`, so the real extraction, span-locating, verification and deterministic
scoring code all still execute. The limitation is honest and explicit — only the three
built-in cases can be analysed, and pasting a custom narrative returns a `422` explaining why.

For live analysis of arbitrary narratives:

```bash
cp .env.example backend/.env    # then set OPENAI_API_KEY
```

### Any OpenAI-compatible provider

You do not need an OpenAI account. Set `OPENAI_BASE_URL` and CausalTrace will run against
Groq, OpenRouter, Together, DeepSeek, or a local Ollama / llama.cpp server:

```bash
# DeepSeek
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-flash
OPENAI_MAX_TOKENS=8192
OPENAI_EXTRA_BODY={"thinking": {"type": "disabled"}}

# Groq free tier
OPENAI_BASE_URL=https://api.groq.com/openai/v1
OPENAI_MODEL=llama-3.3-70b-versatile

# Local Ollama, no key required
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_MODEL=llama3.1
OPENAI_API_KEY=ollama
```

Check any configuration with a single cheap call before running the app:

```bash
cd backend && .venv/bin/python preflight.py
```

`OPENAI_EXTRA_BODY` is merged into every request, which keeps vendor quirks in configuration
rather than in the client. The DeepSeek case is a good example of why it is needed: **thinking
mode is enabled by default, and in thinking mode DeepSeek silently ignores `temperature`** —
documented as "will not trigger an error but will also have no effect." Determinism would be
lost with nothing raised, so the shipped config disables thinking. That also makes
`temperature=0` take effect and cuts cost, and it suits the task — extraction wants verbatim
fidelity, not exploration. Drop the line to let the model reason first.

Strict JSON-schema structured output is an OpenAI extension that most compatible endpoints
implement only partially, so the client **negotiates downward on first use** and remembers
what worked:

| Mode | Request | Typical provider |
| --- | --- | --- |
| `strict` | `response_format=json_schema`, `strict: true` | OpenAI |
| `json_object` | `response_format=json_object` + schema in prompt | Groq, OpenRouter |
| `prompt` | no `response_format`, schema in prompt | everything, incl. local |

Negotiation is driven by the provider actually rejecting the request (HTTP 400), not by
matching model names, which go stale. Authentication and rate-limit errors are **re-raised
immediately** rather than being mistaken for an unsupported format — degrading the output
format cannot fix a bad key.

When a weaker mode is in use the output is no longer schema-enforced, so that is reported as
an analysis warning in the UI and via `GET /api/health`. Parsing tolerates markdown fences and
prose preamble, and the pipeline stages read model output defensively, so a weaker provider
yields **more UNKNOWNs rather than a crash** — the correct failure direction here. Force a mode
with `OPENAI_JSON_MODE` if auto-negotiation misbehaves.

All provider code lives in `backend/services/llm_client.py`; no service module imports a
vendor SDK.

---

## Demo script

1. Open `http://localhost:3000` and load **"Acute liver injury with two candidate drugs"**.
2. Click **Analyze causality**.
3. **Competing causes** — five hypotheses, not one verdict. Note that *"the available evidence
   is insufficient to identify a single cause"* carries **Strong support**, and that Drug B is
   argued *against* because the patient recovered while still taking it.
4. Click any evidence bullet → the exact sentence highlights in the narrative on the left.
   This works from every pane: hypotheses, timeline, Naranjo rows, extracted claims.
5. **Naranjo** — 10 items answered individually with citations, a deterministic total of 3
   ("Possible"), and the instability banner: 5 items UNKNOWN, true range [1, 9].
6. **Extracted evidence** — one claim sits under *"Rejected by verification"* with the
   verifier's reason. Kept visible, not hidden.
7. Load **"Acute kidney injury, minimally reported"** for the abstention case: 7 of 10 items
   UNKNOWN, range [0, 10] — spanning all four bands, so the point score means very little.
8. Load **"Maculopapular rash with positive rechallenge"** for the contrast: a genuinely
   strong case, 10 / Definite, and the classification is **stable**. The system is not merely
   biased toward hedging.

Then run the evaluation:

```bash
backend/.venv/bin/python evaluation/evaluate.py
```

---

## Architecture

```
backend/
  main.py                  FastAPI: /api/health, /api/examples, /api/analyze
  schemas/models.py        Pydantic contracts shared by every stage
  services/
    llm_client.py          the only seam to a provider; OpenAI + Mock
    spans.py               deterministic quote -> character-offset resolution
    extractor.py           stage 1: structured evidence extraction
    verifier.py            independent audit of claims AND Naranjo answers
    timeline.py            stage 2: chronology, relative ordering preserved
    hypotheses.py          stage 3: competing causes, qualitative strength
    naranjo.py             published weight table + pure-Python scorer
    who_umc.py             WHO-UMC category judgement
    pipeline.py            stage orchestration
    cases.py               synthetic demo narratives
  fixtures/<case>/*.json   recorded per-stage output for mock mode
  tests/                   39 tests
  validate_fixtures.py     asserts every fixture quote is verbatim

frontend/
  app/page.tsx             orchestration + shared highlight state
  components/
    CaseInput.tsx          narrative + drug + event, example loader
    EvidencePanel.tsx      the Evidence Inspector (source highlighting)
    CausalGraph.tsx        React Flow competing-cause graph
    HypothesisPanel.tsx    supports / argues-against / not-reported
    Timeline.tsx           chronology with date-certainty labelling
    NaranjoTable.tsx       per-item table, score scale, instability banner
    WhoUmcPanel.tsx        deliberately styled apart from Naranjo
    ClaimsPanel.tsx        extracted claims incl. rejected ones

evaluation/
  cases.json               dataset + author-assigned references
  baselines.py             single-pass verdict, single-pass questionnaire
  evaluate.py              metrics + comparison table
```

**Pipeline order is load-bearing:** extraction → verification → timeline → hypotheses →
Naranjo answering → **Naranjo verification** → deterministic scoring → WHO-UMC. Claims are
audited before the user sees them, and item answers are audited before they can move the
score. Each stage is span-checked first, so an unlocatable quote never reaches an LLM
verifier in the first place.

Each stage has its own narrow prompt. There is deliberately no single agent prompt doing
everything — extraction is told to be comprehensive, the verifier is told only to falsify, and
giving one prompt both jobs is what produces confident wrongness.

---

## Scientific assumptions and decisions

These are choices a reviewer should be able to disagree with, so they are stated explicitly.

- **Naranjo weights** are transcribed from the worksheet as published in LiverTox
  ([NCBI Bookshelf NBK548069](https://www.ncbi.nlm.nih.gov/books/NBK548069/)). Range −4 to
  +13; Definite ≥9, Probable 5–8, Possible 1–4, Doubtful ≤0. Pinned by tests.
- **Item 6 (placebo) is UNKNOWN, not NO, when no placebo was given.** Published case reports
  essentially never administer placebo. Scoring it NO adds +1 to virtually every case for
  something that never happened. This is conservative and it costs the suspected drug a
  point — deliberately.
- **Item 5 (alternative causes) requires positive exclusion to answer NO.** Silence is
  UNKNOWN.
- **Item 4 distinguishes "explicitly not done" from "not reported."** Both score 0, but the
  UI shows the citation when the narrative explicitly says no rechallenge occurred.
- **No inferred dates, including years.** The demo narratives say "3 January" without a year,
  so no ISO date is emitted at all — only a display label. Emitting `2026-01-03` would
  fabricate the year, and temporal sequence is the heaviest-weighted Naranjo element.
- **No numeric causal probabilities.** Qualitative labels only.
- **Drug-class level only.** Demo cases use letter labels plus therapeutic class ("Drug A, an
  oral antifungal agent") rather than product names, per the challenge scope rule. No
  investigational product is analysed as though it had a known adverse-event profile.
- **False negatives are treated as costlier than false alarms.** Wrongly clearing a drug is
  the error that harms patients, so the evaluation reports sensitivity for Probable/Definite
  cases separately from overall agreement.

---

## Evaluation

```bash
backend/.venv/bin/python evaluation/evaluate.py
backend/.venv/bin/python evaluation/evaluate.py --case dili-ambiguous-001
backend/.venv/bin/python evaluation/evaluate.py --json evaluation/results/dev.json
```

Three systems are compared on identical inputs:

| System | What it does |
| --- | --- |
| **Baseline A** | One call: "did this drug cause this event?" → category. No evidence trail. |
| **Baseline B** | One call: fill the whole Naranjo scale *and* report the total. |
| **CausalTrace** | extraction → verification → competing causes → deterministic Naranjo |

Baseline B is the honest comparison, because it isolates a single variable: same scale, same
case, but the model self-reports the total instead of the total being computed from
independently grounded answers.

Reported metrics: category agreement, Naranjo exact / ±1 / MAE, item-level accuracy,
**correct-UNKNOWN rate**, **over-commitment rate** (reference-UNKNOWN items the system
answered anyway — the dangerous direction), sensitivity for Probable/Definite, grounded-item
rate, and unsupported assertion rate.

### Live results (DeepSeek, n=3) — and why they are not as good as they look

Run against `deepseek-flash` on the three dev cases:

| Metric | CausalTrace | Baseline A | Baseline B |
| --- | --- | --- | --- |
| Category agreement | 1.000 | **1.000** | 0.667 |
| Naranjo exact match | 1.000 | n/a | 0.000 |
| Naranjo MAE | 0.000 | n/a | 1.000 |
| Item-level accuracy | 1.000 | n/a | 0.900 |
| Correct-UNKNOWN rate | 1.000 | n/a | 0.800 |
| Over-commitment rate | 0.000 | n/a | 0.200 |
| Grounded item rate | 0.500 | 0.000 | 0.000 |
| Unsupported assertion rate | 0.024 | n/a | n/a |

**I tuned the prompts against these three cases while debugging. These are therefore
training-set numbers, not held-out performance, and the 1.000s should be read as "the
known failure modes on these three cases are fixed" — nothing more.** With n=3 and no
held-out split, they carry essentially no predictive weight. The first thing any serious
evaluation needs is cases the prompts have never seen.

Two results are more robust than the accuracy figures, because they are structural rather
than tuned:

- **Baseline B's self-reported total disagreed with the sum of its own item answers in 3
  of 3 cases.** Not a hand-authored illustration — measured, every time. This is the
  failure CausalTrace cannot have, because Python does the addition.
- **Baseline A matched the reference category on all three cases.** Worth stating plainly:
  on bare category agreement, the naive one-call baseline ties CausalTrace here. Its
  deficit is everything else — no score, no per-item answers, no evidence trail, no
  uncertainty, nothing to audit. If category agreement is all you need, you do not need
  this system.

### What the live runs actually caught

Three real defects surfaced only under a live model, each fixed and pinned by a test:

1. **Item 4 answered NO on "the patient was not re-exposed."** NO (−1) asserts the drug
   *was* readministered without recurrence. Never readministered is UNKNOWN (0). The model
   was penalising the drug for a rechallenge that never happened.
2. **Item 3 answered YES citing "Drug A was discontinued on 20 January."** The quote
   establishes the drug stopped, not that anything improved. The span locator passed it —
   the quote is genuinely in the text — which exposed a gap: verification ran over
   extraction claims but **not** over Naranjo answers. It does now.
3. **The extractor was writing interpretations into claim text** ("pneumonia is a potential
   alternative cause"), which the verifier then correctly rejected because the narrative
   never says that. The interpretation belongs in the slot, not the claim. Fixing the
   prompt to demand factual claim text dropped the unsupported assertion rate from
   **0.121 to 0.030** on the same case.

### A structural limit the live runs exposed

Item 5 answered NO is a *global* negative — "nothing else could have caused this." A
per-quote verifier structurally cannot validate that, because no single sentence carries
it. The verifier initially rejected a correct NO on the grounds that "no other
medications" does not establish that no alternative cause existed — which is, strictly,
true.

The fix was to judge item 5 against the whole narrative with the quote as anchor, rather
than to weaken the verifier or tune until the number matched. The cleaner fix, not done
here, is to let each item cite *multiple* quotes so a global claim can show all its
support. Noted in Limitations.

### Read this before quoting any number

**The current numbers are not a measurement of accuracy, and the harness says so on every
run.** The bundled dataset is synthetic with author-assigned references, and in mock mode
CausalTrace's fixtures and those references share an author — so its agreement is *circular
and near-perfect by construction*. The baseline fixtures are likewise hand-authored
illustrations of documented single-pass failure modes, not observed model output.

What a mock run genuinely demonstrates: the harness works end to end, the metrics compute,
and the deterministic scorer reproduces its inputs. Nothing about accuracy. Use live mode
(above) for numbers that are at least *measured*, even if still tuned and tiny.

### Harvesting real cases from PMC

`evaluation/pmc_ingest.py` automates the route the starter sheet recommends:

```bash
backend/.venv/bin/python evaluation/pmc_ingest.py --limit 40
# review evaluation/pmc_candidates.json, then:
backend/.venv/bin/python evaluation/pmc_ingest.py --append --from evaluation/pmc_candidates.json
```

It searches PubMed for `Case Reports` in the OA subset that mention Naranjo or WHO-UMC,
resolves PMIDs to PMCIDs via the official converter, pulls full text through the BioC API,
and extracts both the patient narrative and any self-reported causality assessment. On a
12-article sample it produced 10 usable candidates.

**Access is via official interfaces only** — E-utilities, the ID converter, `efetch`, and
the BioC API. The PMC website is never scraped, requests are throttled with exponential
backoff (3/s, or 10/s with `NCBI_API_KEY`), and everything is cached, so a re-run costs
NCBI nothing.

Three safeguards worth knowing about, each prompted by something real in the data:

- **Nothing is trusted without review.** Every record is written `needs_review: true`
  alongside the verbatim sentence its score was parsed from. `--append` refuses to add
  unreviewed records, because an unchecked regex silently becoming your ground truth is
  worse than having no ground truth.
- **Licences are checked, and article text is never committed.** The OA subset is not
  uniformly CC-BY — 2 of 10 in the sample were **CC BY-NC-ND**, where "No Derivatives"
  makes redistributing the text in this repo a real problem. Narratives are cached in a
  gitignored directory and `cases.json` stores only a PMCID pointer unless the licence
  clearly permits redistribution. Text *mining* is fine across the subset; redistribution
  is the restricted part.
- **Published values are checked against each other.** One article in the sample reports a
  Naranjo score of 4 while calling it "probable" — but 4 is *Possible* on the published
  scale. Self-reported reference standards contain errors, so score/band disagreements are
  flagged rather than silently accepted.

`truststore` is a dev dependency because NCBI serves a cross-signed chain whose root is
absent from `certifi`; the OS trust store validates it correctly where the bundled one
cannot.

**Or add cases by hand** to `evaluation/cases.json` from the
[PMC Open Access Subset](https://pmc.ncbi.nlm.nih.gov/tools/openftlist) — filter PubMed to the
`Case Reports` publication type, restrict to the OA subset, and keep those that state their
own Naranjo score or WHO-UMC category. Set `reference_source` to `published` with the PMCID.
Retrieve only via E-utilities, the BioC API, FTP, or the cloud service; **bulk scraping of the
PMC website is prohibited** and will get you blocked. Expect published cases to be a biased
sample — journals publish the interesting ones, so Probable and Definite are heavily
over-represented relative to real-world case volume, and overall accuracy on such a set will
flatter any system.

---

## Testing

```bash
cd backend
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q         # 69 tests
.venv/bin/python validate_fixtures.py # 136 fixture quotes must be verbatim
.venv/bin/python preflight.py         # one cheap call; checks provider config
```

The tests pin the published weights, the −4..+13 range, every band boundary, the invariant
that the total always lies inside the resolved-score interval, and — most importantly — that
a claim failing either grounding gate cannot reach the user or the score.

`validate_fixtures.py` exists because the demo's credibility rests on source highlighting
being real. It caught genuine authoring errors during development.

---

## Limitations

Stated plainly, because a causality tool that oversells itself is worse than none.

- **No real-world accuracy number exists yet, and the numbers that do exist are tuned.**
  The prompts were iterated against the same three synthetic cases the evaluation reports
  on, with no held-out split. This is the biggest gap by a wide margin.
- **Global-negative items cannot be properly verified.** Each item cites one quote, but
  item 5 answered NO ("no alternative cause could explain this") is a claim about the
  whole narrative. The current workaround has the verifier judge item 5 against the full
  text; the real fix is multi-quote citations per item.
- **Verification costs an extra LLM call per analysis and can itself over-reject.** It
  rejected a correct item 5 before the workaround. Both gates are conservative by design,
  which means they discard some true signal along with the false.
- **Single-drug assessment.** Naranjo is applied to one suspected drug at a time. The
  competing-hypothesis graph surfaces other candidates but does not score each formally.
- **Naranjo is a poor instrument for hepatotoxicity specifically.** It is not weighted for
  time-to-onset or recovery criteria, and it relies on drug levels that are rarely
  informative in idiosyncratic DILI. RUCAM is the better scale there and is not implemented.
- **No mechanistic reasoning.** No drug-target, pathway, or interaction knowledge is used.
- **No case-report ingestion.** Narratives are pasted in; PMC retrieval is not wired up.
- **English only**, and tuned for prose case reports rather than structured safety reports.
- **The verifier is itself a model** and can err. It reduces unsupported assertions; it does
  not eliminate them. The span locator is deterministic and is the stronger of the two gates.
- **Published narratives omit far more than they state.** No pipeline can recover information
  the report never contained — which is precisely why UNKNOWN is a first-class output.

## Scope and data

Public, appropriately licensed data only. Never patient-identifiable information. Work at the
drug-class or therapeutic-area level; do not present conclusions about named products. Nothing
built here is a medical device or a clinical decision tool.

## License

MIT — see [LICENSE](LICENSE).
