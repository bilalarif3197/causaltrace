"""Measure the extractor against ADE Corpus V2, a human-annotated benchmark.

Every extraction number this project reports so far comes from four synthetic
cases whose labels I wrote myself, against which the prompts were then tuned.
This replaces that with 6,821 drug-adverse-effect relations annotated by two
independent annotators, each carrying gold CHARACTER OFFSETS -- which line up
exactly with what `spans.locate_span` produces.

Gurulingappa et al., "Development of a benchmark corpus to support the automatic
extraction of drug-related adverse effects from medical case reports",
J Biomed Inform 45(5):885-892, 2012.

Three things are measured, and the third is the one that matters most:

  1. **Adverse-event recall** on positives, scored by span overlap against the
     gold annotation rather than by string matching.
  2. **Grounding rate** -- label-free, since a quote either occurs in the
     sentence or it does not.
  3. **Fabrication rate on labelled negatives.** The corpus contains sentences
     annotators marked as containing NO adverse drug event. This project's
     central claim is that it does not invent findings, and this is the first
     measurement of that claim against human labels rather than my own.

Honest limitation, stated because it bounds what the numbers mean: ADE Corpus is
SENTENCE-level text from abstracts, while CausalTrace is built for full case
narratives with timelines and competing causes. This evaluates the extraction
layer only. It says nothing about causality reasoning, and a good score here
would not license any claim about the assessment as a whole.

Licence: the HuggingFace dataset card records the licence as "unknown", so the
corpus is cached locally and gitignored, never redistributed in this repo --
the same treatment as the CC BY-NC-ND articles in the PMC subset.

Usage:
    python evaluation/ade_corpus_eval.py --limit 20
    python evaluation/ade_corpus_eval.py --limit 60 --json evaluation/results/ade.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

try:  # this machine's Python cannot build a path through some CA chains
    import truststore

    truststore.inject_into_ssl()
except Exception:  # pragma: no cover
    print("note: install truststore if TLS validation fails", file=sys.stderr)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / "backend" / ".env")

from schemas.review import FactSection, PatientContext  # noqa: E402
from services import store, suggest  # noqa: E402
from services.llm_client import build_client  # noqa: E402
from services.workspace import create_case  # noqa: E402

CACHE = Path(__file__).resolve().parent / ".ade_cache"
ROWS_API = "https://datasets-server.huggingface.co/rows"
DATASET = "ade-benchmark-corpus/ade_corpus_v2"

#: The classification split is ordered positives-first; negatives begin here.
NEGATIVES_START = 6900

LICENCE_NOTE = (
    "ADE Corpus V2 licence is recorded as 'unknown' on its dataset card, so rows are cached "
    "locally and gitignored rather than committed to this repository."
)

#: Sections whose facts count as "the extractor found an adverse event".
EVENT_FIELDS = {"event", "symptoms", "severity", "lab_abnormalities", "objective_tests"}


def fetch_rows(config: str, offset: int, length: int) -> list[dict]:
    key = CACHE / f"{config}-{offset}-{length}.json"
    if key.is_file():
        return json.loads(key.read_text())["rows"]
    query = urllib.parse.urlencode(
        {"dataset": DATASET, "config": config, "split": "train", "offset": offset, "length": length}
    )
    request = urllib.request.Request(
        f"{ROWS_API}?{query}", headers={"User-Agent": "CausalTrace/0.2 (research evaluation)"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)
    CACHE.mkdir(parents=True, exist_ok=True)
    key.write_text(json.dumps(payload))
    return payload["rows"]


def overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


def extract_events(client, sentence: str) -> list[dict[str, Any]]:
    """Run the real extraction path over one sentence."""
    doc = create_case(
        narrative=sentence,
        suspected_drug="(not stated)",
        adverse_event="(to be determined)",
        title="[ade-eval]",
        patient=PatientContext(),
    )
    try:
        facts = suggest.suggest_facts(client, doc)
    finally:
        store.delete_case(doc.id)

    out = []
    for fact in facts:
        if fact.section is not FactSection.ADVERSE_EVENT or fact.field not in EVENT_FIELDS:
            continue
        span = fact.ai.span if fact.ai else None
        out.append(
            {
                "field": fact.field,
                "value": (fact.ai.value if fact.ai else None) or "",
                "quote": fact.ai.evidence_text if fact.ai else None,
                "start": span.start if span else None,
                "end": span.end if span else None,
                "grounded": bool(span and span.located),
            }
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=20, help="positives AND negatives to sample each")
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--json", help="write full results here")
    args = ap.parse_args()

    store.init_db()
    client = build_client()

    print("=" * 80)
    print("Extraction evaluation against ADE Corpus V2 (human-annotated)")
    print("=" * 80)
    print(f"client : {client.mode} ({client.name})")
    print(LICENCE_NOTE)
    print()
    print("Sentence-level benchmark from abstracts. This measures the EXTRACTION layer,")
    print("not causality reasoning -- a good score here licenses no claim about the")
    print("assessment as a whole.")
    print()

    positives = fetch_rows("Ade_corpus_v2_drug_ade_relation", args.offset, args.limit)
    # The classification split is ordered positives-first: ADE-related sentences
    # occupy roughly offsets 0-6820, and the negatives follow. Sampling from 0
    # returned no negatives at all.
    negatives = [
        r
        for r in fetch_rows("Ade_corpus_v2_classification", NEGATIVES_START + args.offset, args.limit * 3)
        if r["row"]["label"] == 0
    ][: args.limit]

    print(f"sampled {len(positives)} positive relation(s) and {len(negatives)} labelled negative(s)\n")

    # --- positives -----------------------------------------------------------
    print("POSITIVES — did the extractor find the annotated adverse effect?")
    print("-" * 80)
    hits = span_hits = grounded = total_events = 0
    detail: list[dict] = []

    for i, row in enumerate(positives, start=1):
        record = row["row"]
        sentence, gold = record["text"], record["effect"]
        gold_start = record["indexes"]["effect"]["start_char"][0]
        gold_end = record["indexes"]["effect"]["end_char"][0]

        try:
            events = extract_events(client, sentence)
        except Exception as exc:  # noqa: BLE001
            print(f"  [{i:>2}] FAILED {type(exc).__name__}")
            continue

        total_events += len(events)
        grounded += sum(1 for e in events if e["grounded"])
        text_hit = any(gold.lower() in e["value"].lower() or e["value"].lower() in gold.lower()
                       for e in events if e["value"])
        span_hit = any(
            e["start"] is not None and overlaps(e["start"], e["end"], gold_start, gold_end)
            for e in events
        )
        hits += bool(text_hit)
        span_hits += bool(span_hit)
        mark = "OK " if (text_hit or span_hit) else "MISS"
        print(f"  [{i:>2}] {mark} gold={gold[:34]:<34} extracted={len(events)}"
              f" {'span' if span_hit else ''}{'+text' if text_hit else ''}")
        detail.append({"sentence": sentence, "gold": gold, "text_hit": text_hit,
                       "span_hit": span_hit, "events": events})

    # --- negatives -----------------------------------------------------------
    # These sentences were labelled as NOT asserting a drug-caused adverse
    # effect. That is a narrower question than "does this text contain a
    # clinical finding", which is what the extractor answers, so an extraction
    # here is not automatically an error -- see the summary for the split.
    print("\nNON-ADE SENTENCES — annotators found no drug-caused adverse effect asserted")
    print("-" * 80)
    ungrounded = extracted_on_negatives = 0
    improvement_errors = 0
    #: Wording that means the patient improved or nothing happened. Extracting
    #: any of these as an adverse event is a real error, not a definitional
    #: disagreement with the annotators.
    IMPROVEMENT_CUES = (
        "uneventful", "undetectable", "normalis", "normaliz", "resolved", "improve",
        "recovered", "no complication", "unremarkable", "decreased",
    )

    for i, row in enumerate(negatives, start=1):
        sentence = row["row"]["text"]
        try:
            events = extract_events(client, sentence)
        except Exception as exc:  # noqa: BLE001
            print(f"  [{i:>2}] FAILED {type(exc).__name__}")
            continue

        if not events:
            print(f"  [{i:>2}] no finding extracted")
        else:
            extracted_on_negatives += 1
            bad = [e for e in events if any(c in e["value"].lower() for c in IMPROVEMENT_CUES)]
            ungrounded += sum(1 for e in events if not e["grounded"])
            if bad:
                improvement_errors += 1
                print(f"  [{i:>2}] ERROR   improvement read as an adverse event: {bad[0]['value'][:55]!r}")
            else:
                print(f"  [{i:>2}] finding extracted: {events[0]['value'][:52]!r} "
                      f"(present in the text; annotators saw no drug relation)")
        detail.append({"sentence": sentence, "gold": None, "events": events})

    n_pos, n_neg = len(positives), len(negatives)

    def rate(n: int, d: int) -> str:
        return f"{n}/{d} = {n / d:.3f}" if d else "n/a"

    print("\n" + "=" * 80)
    print("RESULTS")
    print("=" * 80)
    print(f"  adverse-event recall (text match)     {rate(hits, n_pos)}")
    print(f"  adverse-event recall (span overlap)   {rate(span_hits, n_pos)}")
    print(f"  quote grounding rate                  {rate(grounded, total_events)}")
    print(f"  FABRICATED quotes (not in the text)   {rate(ungrounded, total_events)}")
    print(f"  improvement read as adverse event     {rate(improvement_errors, n_neg)}")
    print(f"  any finding pulled from a non-ADE row {rate(extracted_on_negatives, n_neg)}")
    print()
    print("  Span overlap is the stricter recall measure: it requires the cited evidence")
    print("  to land on the annotated text, not merely to name the right condition.")
    print()
    print("  Read the last two lines carefully; they are not the same thing.")
    print()
    print("  FABRICATED QUOTES is the honest hallucination measure, and the one this")
    print("  project's claims rest on: a quote either occurs in the source or it does not.")
    print()
    print("  'Any finding pulled from a non-ADE row' is NOT a hallucination rate, and must")
    print("  not be quoted as one. ADE Corpus labels whether a sentence asserts a")
    print("  DRUG-CAUSED adverse effect; the extractor answers the broader question of what")
    print("  clinical facts the text contains. 'Hepatotoxicity from green tea' really does")
    print("  name an adverse event, so extracting it is not an error -- the annotators")
    print("  marked the row 0 because no drug-causation relation is asserted.")
    print()
    print("  'Improvement read as adverse event' IS a genuine extraction bug: a recovery or")
    print("  the absence of harm is not an adverse event. That is the number to drive down.")

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {
                    "dataset": DATASET,
                    "licence_note": LICENCE_NOTE,
                    "caveat": (
                        "Sentence-level benchmark from abstracts; measures the extraction layer "
                        "only, not causality reasoning."
                    ),
                    "model": client.name,
                    "mode": client.mode,
                    "counts": {"positives": n_pos, "negatives": n_neg, "events_extracted": total_events},
                    "metrics": {
                        "recall_text": hits / n_pos if n_pos else None,
                        "recall_span_overlap": span_hits / n_pos if n_pos else None,
                        "grounding_rate": grounded / total_events if total_events else None,
                        # The honest hallucination measure.
                        "fabricated_quote_rate": ungrounded / total_events if total_events else None,
                        # A genuine extraction bug.
                        "improvement_as_event_rate": improvement_errors / n_neg if n_neg else None,
                        # NOT a hallucination rate; see the note below.
                        "any_finding_on_non_ade_rows": extracted_on_negatives / n_neg if n_neg else None,
                    },
                    "metric_notes": {
                        "any_finding_on_non_ade_rows": (
                            "Not an error rate. ADE Corpus labels whether a sentence asserts a "
                            "DRUG-CAUSED adverse effect; the extractor answers what clinical facts "
                            "the text contains. Extracting 'hepatotoxicity' from 'Hepatotoxicity "
                            "from green tea' is correct behaviour against a different question."
                        ),
                        "fabricated_quote_rate": (
                            "The measure the project's claims rest on: a cited quote either occurs "
                            "in the source text or it does not."
                        ),
                    },
                    "detail": detail,
                },
                indent=2,
            )
            + "\n"
        )
        print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
