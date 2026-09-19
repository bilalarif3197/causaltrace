"""Evaluate the AI assistance, not the verdict.

The claim this harness is built to test is NOT "our AI is more accurate than a
clinician". It is:

    Structured AI assistance produces more traceable, complete and reviewable
    causality assessments than an unstructured AI response.

That reframing matters because most of these metrics need no gold labels at
all. Whether a cited quote actually occurs in the narrative is checkable
deterministically; whether a single-pass verdict carries any evidence trail is
checkable by construction. Those numbers are therefore real measurements, not
agreement with something a human (or the same author) wrote down.

Metrics
  grounding rate          extracted facts whose quote is located in the source
  verification pass rate  facts whose quote survives the independent audit
  unsupported rate        fabricated citations + failed verification
  traceable elements      assessment elements carrying a source span
  unknown handling        Naranjo items correctly left UNKNOWN
  alternative recall      documented competing causes surfaced (needs labels)
  item accuracy           Naranjo item agreement (needs labels)
  reviewer corrections    measured from real review sessions in the database

Run:
    python evaluation/evaluate_assistance.py
    python evaluation/evaluate_assistance.py --case tmpsmx-dili-004
    python evaluation/evaluate_assistance.py --json evaluation/results/assist.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / "backend" / ".env")

from baselines import baseline_a  # noqa: E402
from schemas.review import Answer, PatientContext, ReviewerStatus, Verdict  # noqa: E402
from services import cases as demo_cases  # noqa: E402
from services import store, suggest, workspace  # noqa: E402
from services.assessment import score_framework  # noqa: E402
from services.llm_client import MockUnavailable, build_client  # noqa: E402

DATASET = Path(__file__).resolve().parent / "cases.json"


def load_reference() -> dict[str, dict]:
    data = json.loads(DATASET.read_text())
    return {c["case_id"]: c for c in data["cases"]}


def pct(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


def assess_case(client, demo, reference: dict | None) -> dict[str, Any]:
    """Run the assisted pipeline over one case and measure the assistance."""
    doc = workspace.create_case(
        narrative=demo.narrative,
        suspected_drug=demo.suspected_drug,
        adverse_event=demo.adverse_event,
        title=f"[eval] {demo.title}",
        patient=PatientContext(
            indication=demo.indication,
            age=demo.age,
            sex=demo.sex,
            concomitant_medications=demo.concomitant_medications,
            comorbidities=demo.comorbidities,
        ),
        demo_case_id=demo.case_id,
    )

    for stage in ("facts", "hypotheses", "naranjo"):
        doc, _ = workspace.run_suggest(client, doc, stage)

    # --- Grounding: does each cited quote exist in the source at all? --------
    facts = doc.facts
    with_quote = [f for f in facts if f.ai and f.ai.evidence_text]
    located = [f for f in with_quote if f.ai.grounded]

    verified = [f for f in facts if f.ai and f.ai.verification is Verdict.SUPPORTED]
    partial = [f for f in facts if f.ai and f.ai.verification is Verdict.PARTIALLY_SUPPORTED]
    failed = [f for f in facts if f.ai and f.ai.verification is Verdict.NOT_SUPPORTED]
    unsupported = len(with_quote) - len(located) + len(failed)

    # --- Traceability: assessment elements carrying a source span -----------
    traceable = sum(1 for i in doc.naranjo if i.ai and i.ai.grounded)
    answered = sum(1 for i in doc.naranjo if i.ai_answer and i.ai_answer is not Answer.UNKNOWN)

    # --- Unknown handling ----------------------------------------------------
    ai_unknown = sum(1 for i in doc.naranjo if i.ai_answer is Answer.UNKNOWN)
    correct_unknown = expected_unknown = item_hits = item_total = None
    if reference and reference.get("reference_item_answers"):
        ref_items = reference["reference_item_answers"]
        expected_unknown = sum(1 for v in ref_items.values() if v == "UNKNOWN")
        correct_unknown = sum(
            1
            for n, v in ref_items.items()
            if v == "UNKNOWN"
            and next((i.ai_answer for i in doc.naranjo if i.number == int(n)), None) is Answer.UNKNOWN
        )
        item_total = len(ref_items)
        item_hits = sum(
            1
            for n, v in ref_items.items()
            if next((i.ai_answer.value for i in doc.naranjo if i.number == int(n) and i.ai_answer), None) == v
        )

    # --- Alternative-cause recall -------------------------------------------
    alt_hits = alt_total = None
    documented = (reference or {}).get("documented_alternatives") or []
    if documented:
        labels = " ".join(h.label.lower() for h in doc.hypotheses)
        alt_total = len(documented)
        alt_hits = sum(1 for alt in documented if alt.lower() in labels)

    # --- Simulated full acceptance, to show the framework can be reached ----
    simulated = [i.model_copy(deep=True) for i in doc.naranjo]
    for item in simulated:
        if item.ai_answer:
            item.reviewer_answer = item.ai_answer
            item.reviewer_status = ReviewerStatus.ACCEPTED
    framework = score_framework(simulated)

    store.delete_case(doc.id)  # evaluation runs leave no cases behind

    return {
        "case_id": demo.case_id,
        "facts_extracted": len(facts),
        "facts_with_quote": len(with_quote),
        "facts_located": len(located),
        "grounding_rate": pct(len(located), len(with_quote)),
        "verification_supported": len(verified),
        "verification_partial": len(partial),
        "verification_failed": len(failed),
        "verification_pass_rate": pct(len(verified), len(with_quote)),
        "unsupported_rate": pct(unsupported, len(with_quote)),
        "naranjo_traceable": traceable,
        "naranjo_answered": answered,
        "traceability_rate": pct(traceable, answered),
        "ai_unknown_count": ai_unknown,
        "expected_unknown": expected_unknown,
        "correct_unknown": correct_unknown,
        "correct_unknown_rate": pct(correct_unknown or 0, expected_unknown or 0),
        "item_accuracy": pct(item_hits or 0, item_total or 0),
        "alternatives_surfaced": alt_hits,
        "alternatives_documented": alt_total,
        "alternative_recall": pct(alt_hits or 0, alt_total or 0),
        "hypotheses_total": len(doc.hypotheses),
        "framework_if_all_accepted": f"{framework.total_score} ({framework.classification})",
    }


def assess_baseline(client, demo) -> dict[str, Any]:
    out = baseline_a(
        client,
        narrative=demo.narrative,
        suspected_drug=demo.suspected_drug,
        adverse_event=demo.adverse_event,
        case_id=demo.case_id,
    )
    # A single-pass verdict has no evidence trail, no items and no explicit
    # unknowns. These zeros are structural, not a bad score.
    return {
        "case_id": demo.case_id,
        "category": out["category"],
        "facts_extracted": 0,
        "traceable_elements": 0,
        "explicit_unknowns": 0,
        "alternatives_surfaced": 0,
        "reviewable_units": 1,
    }


def measure_real_corrections() -> dict[str, Any]:
    """Reviewer correction rate, from actual sessions in the database.

    This is the one metric that cannot be simulated: it needs a human to have
    disagreed with something. Zero cases means zero evidence, not a good score.
    """
    from services.assessment import compute_stats

    suggestions = corrections = reviewed_cases = 0
    for summary in store.list_cases():
        doc = store.get_case(summary.id)
        if doc is None:
            continue
        stats = compute_stats(doc)
        if stats.ai_suggestions_total == 0:
            continue
        reviewed_cases += 1
        suggestions += stats.ai_suggestions_total
        corrections += stats.reviewer_corrections
    return {
        "cases_with_review": reviewed_cases,
        "ai_suggestions": suggestions,
        "reviewer_corrections": corrections,
        "correction_rate": pct(corrections, suggestions),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case", help="restrict to one demo case id")
    ap.add_argument("--json", help="write full results here")
    ap.add_argument("--skip-baseline", action="store_true")
    args = ap.parse_args()

    store.init_db()
    client = build_client()
    reference = load_reference()

    demos = [c for c in demo_cases.EXAMPLE_CASES if not args.case or c.case_id == args.case]
    if not demos:
        raise SystemExit(f"No demo case '{args.case}'.")

    print("=" * 84)
    print("CausalTrace — AI assistance evaluation")
    print("=" * 84)
    print(f"client : {client.mode} ({client.name})")
    print(f"cases  : {len(demos)}")
    print()
    print("Testing whether structured assistance is more traceable and reviewable than a")
    print("single-pass answer -- NOT whether it out-diagnoses a clinician.")
    print()
    print("Grounding, verification, traceability and unsupported-rate need no gold labels:")
    print("they are checked against the narrative itself, so they are real measurements.")
    print("Item accuracy and alternative recall DO use author-assigned labels on synthetic")
    print("cases and carry all the caveats in cases.json.")
    print()

    assisted: list[dict] = []
    baseline: list[dict] = []

    for demo in demos:
        print(f"  {demo.case_id} ...", end="", flush=True)
        try:
            assisted.append(assess_case(client, demo, reference.get(demo.case_id)))
            if not args.skip_baseline:
                baseline.append(assess_baseline(client, demo))
            print(" done")
        except MockUnavailable as exc:
            print(f" skipped ({exc})")
        except Exception as exc:  # noqa: BLE001
            print(f" FAILED: {type(exc).__name__}: {exc}")

    if not assisted:
        print("\nNo cases evaluated.")
        return 1

    def avg(key: str) -> float | None:
        vals = [r[key] for r in assisted if r.get(key) is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    total_quotes = sum(r["facts_with_quote"] for r in assisted)
    total_located = sum(r["facts_located"] for r in assisted)

    print()
    print("ASSISTANCE QUALITY (label-free — measured against the narrative)")
    print("-" * 84)
    rows = [
        ("Facts extracted", sum(r["facts_extracted"] for r in assisted)),
        ("Facts carrying a quote", total_quotes),
        ("Quote located in source", f"{total_located}  ({pct(total_located, total_quotes)})"),
        ("Verification passed", sum(r["verification_supported"] for r in assisted)),
        ("Verification partial", sum(r["verification_partial"] for r in assisted)),
        ("Verification failed", sum(r["verification_failed"] for r in assisted)),
        ("Unsupported assertion rate", avg("unsupported_rate")),
        ("Naranjo traceability rate", avg("traceability_rate")),
    ]
    for label, value in rows:
        print(f"  {label:<32} {value}")

    print()
    print("ASSISTANCE QUALITY (against author-assigned labels — see caveats)")
    print("-" * 84)
    for label, key in [
        ("Correct-UNKNOWN rate", "correct_unknown_rate"),
        ("Naranjo item accuracy", "item_accuracy"),
        ("Alternative-cause recall", "alternative_recall"),
    ]:
        print(f"  {label:<32} {avg(key)}")

    if baseline:
        print()
        print("STRUCTURAL COMPARISON vs SINGLE-PASS BASELINE")
        print("-" * 84)
        print(f"  {'':<32}{'assisted':>14}{'single-pass':>16}")
        print(f"  {'Facts surfaced for review':<32}"
              f"{sum(r['facts_extracted'] for r in assisted):>14}"
              f"{sum(r['facts_extracted'] for r in baseline):>16}")
        print(f"  {'Elements with a source span':<32}"
              f"{sum(r['naranjo_traceable'] for r in assisted):>14}"
              f"{sum(r['traceable_elements'] for r in baseline):>16}")
        print(f"  {'Alternatives surfaced':<32}"
              f"{sum(r['hypotheses_total'] for r in assisted):>14}"
              f"{sum(r['alternatives_surfaced'] for r in baseline):>16}")
        print(f"  {'Explicit UNKNOWNs':<32}"
              f"{sum(r['ai_unknown_count'] for r in assisted):>14}"
              f"{sum(r['explicit_unknowns'] for r in baseline):>16}")
        print(f"  {'Independently reviewable units':<32}"
              f"{sum(r['facts_extracted'] + 10 for r in assisted):>14}"
              f"{sum(r['reviewable_units'] for r in baseline):>16}")
        print()
        print("  The baseline's zeros are structural, not a low score: a one-call verdict has")
        print("  no items to check, no spans to trace and nothing a reviewer can accept or")
        print("  reject piece by piece. That is the whole argument.")

    corrections = measure_real_corrections()
    print()
    print("REVIEWER CORRECTION RATE (from real review sessions)")
    print("-" * 84)
    if corrections["cases_with_review"] == 0:
        print("  No reviewed cases in the database yet. This metric cannot be simulated —")
        print("  it requires a human to have actually disagreed with something. Review a")
        print("  case in the app, then re-run.")
    else:
        print(f"  cases with review        {corrections['cases_with_review']}")
        print(f"  AI suggestions           {corrections['ai_suggestions']}")
        print(f"  reviewer corrections     {corrections['reviewer_corrections']}")
        print(f"  correction rate          {corrections['correction_rate']}")
        print("  A rate near zero usually means the review was not adversarial enough,")
        print("  not that the AI was perfect.")

    print()
    print("Per-case detail")
    print("-" * 84)
    for r in assisted:
        print(f"  {r['case_id']:<22} facts={r['facts_extracted']:>3} "
              f"grounded={r['grounding_rate']} verified={r['verification_pass_rate']} "
              f"hypotheses={r['hypotheses_total']} framework={r['framework_if_all_accepted']}")

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {
                    "mode": client.mode,
                    "model": client.name,
                    "assisted": assisted,
                    "baseline": baseline,
                    "reviewer_corrections": corrections,
                },
                indent=2,
            )
            + "\n"
        )
        print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
