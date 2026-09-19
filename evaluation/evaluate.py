"""Compare CausalTrace against single-pass LLM baselines.

Run:
    python evaluation/evaluate.py                # all cases, all systems
    python evaluation/evaluate.py --case <id>
    python evaluation/evaluate.py --json out.json

Metrics reported per system:

  category agreement       fraction matching the reference causality band
  score MAE / exact / ±1   Naranjo score agreement (systems that produce one)
  item accuracy            per-item YES/NO/UNKNOWN agreement across all items
  correct-UNKNOWN rate     of reference-UNKNOWN items, fraction marked UNKNOWN
  over-commitment rate     of reference-UNKNOWN items, fraction answered YES/NO.
                           This is the dangerous direction: asserting a fact the
                           narrative never reported.
  sensitivity              of reference Probable/Definite cases, fraction the
                           system also rated Probable/Definite. Under-calling a
                           real association is the error that harms patients.
  grounded items           fraction of item answers carrying a locatable source
                           span. Structurally 0 for both baselines.
  unsupported rate         claims whose cited evidence failed verification

Nothing here fabricates results: every number is computed from actual system
output on the cases in cases.json. But see the loud banner about what the
current dev set can and cannot tell you.
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

# Load backend/.env explicitly. python-dotenv's search starts from the calling
# file's directory, which is evaluation/, so the default would miss it.
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / "backend" / ".env")

from baselines import baseline_a, baseline_b  # noqa: E402
from schemas.models import AnalyzeRequest  # noqa: E402
from services import cases as builtin_cases  # noqa: E402
from services.llm_client import MockUnavailable, build_client  # noqa: E402
from services.pipeline import run_analysis  # noqa: E402

DATASET = Path(__file__).resolve().parent / "cases.json"
STRONG = {"Definite", "Probable"}


NARRATIVE_CACHE = Path(__file__).resolve().parent / ".pmc_cache" / "narratives"


def load_cases() -> tuple[dict, list[dict]]:
    """Resolve each case's narrative, in order of preference.

    1. Inlined in cases.json.
    2. A built-in demo case, whose text lives in backend/services/cases.py so
       there is a single source of truth.
    3. The gitignored PMC narrative cache. Harvested article text is
       third-party content under assorted licences (the OA subset includes
       CC BY-NC-ND), so it is deliberately never committed.
    """
    data = json.loads(DATASET.read_text())
    rows = []
    missing: list[str] = []

    for case in data["cases"]:
        narrative = case.get("narrative")
        if not narrative:
            builtin = builtin_cases.get(case["case_id"])
            if builtin is not None:
                narrative = builtin.narrative
        if not narrative and case.get("pmcid"):
            cached = NARRATIVE_CACHE / f"{case['pmcid']}.txt"
            if cached.is_file():
                narrative = cached.read_text(encoding="utf-8")
            else:
                missing.append(case["case_id"])
                continue
        if not narrative:
            missing.append(case["case_id"])
            continue
        rows.append({**case, "narrative": narrative})

    if missing:
        print(
            f"warning: skipped {len(missing)} case(s) with no available narrative "
            f"({', '.join(missing[:5])}{'...' if len(missing) > 5 else ''}).\n"
            f"         Re-fetch the text with: python evaluation/pmc_ingest.py",
            file=sys.stderr,
        )
    return data["dataset"], rows


def run_causaltrace(client, case: dict) -> dict:
    result = run_analysis(
        client,
        AnalyzeRequest(
            narrative=case["narrative"],
            suspected_drug=case["suspected_drug"],
            adverse_event=case["adverse_event"],
            case_id=case["case_id"],
            run_who_umc=False,
        ),
    )
    return {
        "system": "causaltrace",
        "category": result.naranjo.classification,
        "score": result.naranjo.total_score,
        "self_reported_total": None,
        "items": {i.number: i.answer.value for i in result.naranjo.items},
        "grounded_items": sum(1 for i in result.naranjo.items if i.span and i.span.start is not None),
        "unsupported_rate": result.unsupported_assertion_rate,
        "unknown_count": result.naranjo.unknown_count,
        "score_floor": result.naranjo.score_floor,
        "score_ceiling": result.naranjo.score_ceiling,
        "classification_is_stable": result.naranjo.classification_is_stable,
        "explanation": "",
    }


def aggregate(per_case: list[dict]) -> dict[str, Any]:
    """Collapse per-case runs into the reported metrics."""
    cat_hits = cat_total = 0
    exact = within1 = score_total = 0
    abs_err = 0.0
    item_hits = item_total = 0
    unk_hits = unk_total = 0
    sens_hits = sens_total = 0
    grounded = items_seen = 0
    unsupported: list[float] = []
    mismatched_self_reports = 0

    for run in per_case:
        ref = run["reference"]
        out = run["output"]

        if ref["reference_naranjo_category"] and out.get("category"):
            cat_total += 1
            cat_hits += out["category"] == ref["reference_naranjo_category"]

            if ref["reference_naranjo_category"] in STRONG:
                sens_total += 1
                sens_hits += out["category"] in STRONG

        if ref["reference_naranjo_score"] is not None and out.get("score") is not None:
            score_total += 1
            diff = abs(out["score"] - ref["reference_naranjo_score"])
            abs_err += diff
            exact += diff == 0
            within1 += diff <= 1

        ref_items = ref.get("reference_item_answers") or {}
        for number, expected in ref_items.items():
            got = out.get("items", {}).get(int(number))
            if got is None:
                continue
            item_total += 1
            item_hits += got == expected
            if expected == "UNKNOWN":
                unk_total += 1
                unk_hits += got == "UNKNOWN"

        if out.get("items"):
            items_seen += len(out["items"])
            grounded += out.get("grounded_items", 0)
        if out.get("unsupported_rate") is not None:
            unsupported.append(out["unsupported_rate"])
        if out.get("recomputed_matches_self_report") is False:
            mismatched_self_reports += 1

    def ratio(n: int, d: int) -> float | None:
        return round(n / d, 4) if d else None

    return {
        "n_cases": len(per_case),
        "category_agreement": ratio(cat_hits, cat_total),
        "score_exact": ratio(exact, score_total),
        "score_within_1": ratio(within1, score_total),
        "score_mae": round(abs_err / score_total, 3) if score_total else None,
        "item_accuracy": ratio(item_hits, item_total),
        "correct_unknown_rate": ratio(unk_hits, unk_total),
        "over_commitment_rate": ratio(unk_total - unk_hits, unk_total),
        "sensitivity_probable_definite": ratio(sens_hits, sens_total),
        "grounded_item_rate": ratio(grounded, items_seen),
        "unsupported_assertion_rate": round(sum(unsupported) / len(unsupported), 4)
        if unsupported
        else None,
        "self_reported_total_mismatches": mismatched_self_reports,
    }


SYSTEMS = {
    "causaltrace": run_causaltrace,
    "baseline_a": lambda client, case: baseline_a(
        client,
        narrative=case["narrative"],
        suspected_drug=case["suspected_drug"],
        adverse_event=case["adverse_event"],
        case_id=case["case_id"],
    ),
    "baseline_b": lambda client, case: baseline_b(
        client,
        narrative=case["narrative"],
        suspected_drug=case["suspected_drug"],
        adverse_event=case["adverse_event"],
        case_id=case["case_id"],
    ),
}

ROW_LABELS = [
    ("category_agreement", "Category agreement", "higher"),
    ("score_exact", "Naranjo exact match", "higher"),
    ("score_within_1", "Naranjo within +/-1", "higher"),
    ("score_mae", "Naranjo MAE", "lower"),
    ("item_accuracy", "Item-level accuracy", "higher"),
    ("correct_unknown_rate", "Correct-UNKNOWN rate", "higher"),
    ("over_commitment_rate", "Over-commitment rate", "lower"),
    ("sensitivity_probable_definite", "Sensitivity (prob/def)", "higher"),
    ("grounded_item_rate", "Grounded item rate", "higher"),
    ("unsupported_assertion_rate", "Unsupported assertion rate", "lower"),
]


def fmt(v: Any) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)


def main() -> int:
    ap = argparse.ArgumentParser(description="Evaluate CausalTrace against LLM baselines.")
    ap.add_argument("--case", help="Evaluate a single case id.")
    ap.add_argument("--json", help="Write full results to this path.")
    ap.add_argument(
        "--system", action="append", choices=list(SYSTEMS), help="Restrict to these systems."
    )
    args = ap.parse_args()

    meta, rows = load_cases()
    if args.case:
        rows = [r for r in rows if r["case_id"] == args.case]
        if not rows:
            raise SystemExit(f"No case with id '{args.case}'.")

    client = build_client()
    systems = args.system or list(SYSTEMS)

    print("=" * 78)
    print("CausalTrace evaluation")
    print("=" * 78)
    print(f"dataset : {meta['name']} v{meta['version']}")
    print(f"cases   : {len(rows)}")
    print(f"client  : {client.mode} ({client.name})")

    provenance = {r.get("reference_source") for r in rows}
    if provenance == {"author-assigned"}:
        print()
        print("!! Reference values on this set are AUTHOR-ASSIGNED on SYNTHETIC narratives.")
        print("!! These numbers measure self-consistency and guard against regressions.")
        print("!! They are NOT real-world accuracy and must not be reported as such.")
    if client.mode == "mock":
        print()
        print("!! MOCK MODE -- THESE NUMBERS ARE NOT A MEASUREMENT.")
        print("!! CausalTrace's recorded fixtures and the reference answers in cases.json were")
        print("!! authored by the same hand, so its agreement here is CIRCULAR and near-perfect")
        print("!! by construction. The baseline fixtures are likewise hand-authored")
        print("!! illustrations of known single-pass failure modes, not observed model output.")
        print("!! What this run does prove: the harness works end to end, the metrics compute,")
        print("!! and the deterministic scorer reproduces its inputs. Nothing about accuracy.")
        print("!! Set OPENAI_API_KEY and add published cases for a real comparison.")
    print()

    results: dict[str, Any] = {"dataset": meta, "mode": client.mode, "model": client.name, "systems": {}}

    for system in systems:
        per_case = []
        for case in rows:
            try:
                out = SYSTEMS[system](client, case)
            except MockUnavailable as exc:
                print(f"  skip {system}/{case['case_id']}: {exc}")
                continue
            per_case.append({"case_id": case["case_id"], "reference": case, "output": out})
        if not per_case:
            continue
        results["systems"][system] = {
            "metrics": aggregate(per_case),
            "per_case": [
                {
                    "case_id": r["case_id"],
                    "reference_score": r["reference"]["reference_naranjo_score"],
                    "reference_category": r["reference"]["reference_naranjo_category"],
                    **{k: v for k, v in r["output"].items() if k != "explanation"},
                }
                for r in per_case
            ],
        }

    present = [s for s in systems if s in results["systems"]]
    if not present:
        print("No system produced results.")
        return 1

    width = 22
    # Widest label is "Unsupported assertion rate (v)" at 30 chars.
    label_w = max(32, *(len(lbl) + 4 for _, lbl, _ in ROW_LABELS))
    print(f"{'METRIC':<{label_w}}" + "".join(f"{s:>{width}}" for s in present))
    print("-" * (label_w + width * len(present)))
    for key, label, direction in ROW_LABELS:
        arrow = "^" if direction == "higher" else "v"
        line = f"{label + ' (' + arrow + ')':<{label_w}}"
        for s in present:
            line += f"{fmt(results['systems'][s]['metrics'].get(key)):>{width}}"
        print(line)

    print()
    print("Per-case Naranjo scores")
    print("-" * 78)
    print(f"{'case':<24}{'ref':>6}" + "".join(f"{s:>18}" for s in present))
    for case in rows:
        line = f"{case['case_id']:<24}{fmt(case['reference_naranjo_score']):>6}"
        for s in present:
            row = next(
                (c for c in results["systems"][s]["per_case"] if c["case_id"] == case["case_id"]),
                None,
            )
            if row is None:
                line += f"{'-':>18}"
            else:
                score = fmt(row.get("score"))
                cat = (row.get("category") or "?")[:4]
                line += f"{score + ' ' + cat:>18}"
        print(line)

    # Baseline B self-reports its own total; flag when it cannot add up its own
    # worksheet, since that is an error CausalTrace cannot make by construction.
    b = results["systems"].get("baseline_b", {}).get("metrics", {})
    if b.get("self_reported_total_mismatches"):
        print()
        print(
            f"note: baseline_b's self-reported total disagreed with the sum of its own item "
            f"answers in {b['self_reported_total_mismatches']} of {b['n_cases']} case(s). "
            f"CausalTrace computes the total in Python, so this failure is impossible by design."
        )

    ct = results["systems"].get("causaltrace", {}).get("per_case", [])
    unstable = [c["case_id"] for c in ct if c.get("classification_is_stable") is False]
    if unstable:
        print()
        print(
            f"note: CausalTrace flagged {len(unstable)} of {len(ct)} case(s) as having an unstable "
            f"classification given UNKNOWN items ({', '.join(unstable)}). The baselines report a "
            f"point estimate with no such caveat."
        )

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(results, indent=2) + "\n")
        print(f"\nWrote {out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
