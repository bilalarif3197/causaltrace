"""Check that every quote in every fixture is genuinely verbatim.

The demo's credibility rests on source highlighting actually working, so this
asserts that each non-null `evidence_text` in the recorded fixtures resolves to
an EXACT span of its case narrative. Fuzzy or normalized matches are reported
as warnings: they would still highlight in the UI, but they mean the fixture
quote was retyped rather than copied, and drift is worth knowing about.

Run: python validate_fixtures.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from services import cases  # noqa: E402
from services.llm_client import FIXTURE_ROOT  # noqa: E402
from services.spans import locate_span  # noqa: E402

STAGES = ["extraction", "timeline", "hypotheses", "verification", "naranjo", "who_umc"]


def walk_quotes(node, path="$"):
    """Yield (json_path, quote) for every evidence_text in a nested structure."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "evidence_text" and isinstance(value, str):
                yield f"{path}.{key}", value
            else:
                yield from walk_quotes(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from walk_quotes(item, f"{path}[{i}]")


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []
    checked = 0

    case_dirs = sorted(p for p in FIXTURE_ROOT.iterdir() if p.is_dir())
    if not case_dirs:
        print("No fixtures found.")
        return 1

    for case_dir in case_dirs:
        case = cases.get(case_dir.name)
        if case is None:
            errors.append(f"{case_dir.name}: fixture directory has no matching case in cases.py")
            continue

        present = {p.stem for p in case_dir.glob("*.json")}
        for missing in [s for s in STAGES if s not in present]:
            errors.append(f"{case_dir.name}: missing stage fixture '{missing}.json'")

        for stage_file in sorted(case_dir.glob("*.json")):
            try:
                data = json.loads(stage_file.read_text())
            except json.JSONDecodeError as exc:
                errors.append(f"{case_dir.name}/{stage_file.name}: invalid JSON -- {exc}")
                continue

            for json_path, quote in walk_quotes(data):
                checked += 1
                span = locate_span(case.narrative, quote)
                where = f"{case_dir.name}/{stage_file.name} {json_path}"
                if span is None or not span.located:
                    errors.append(f"{where}: quote NOT FOUND in narrative -> {quote[:70]!r}")
                elif span.locator != "exact":
                    warnings.append(
                        f"{where}: matched via '{span.locator}' "
                        f"(ratio {span.match_ratio}) -> {quote[:70]!r}"
                    )

    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")

    print(f"\n{checked} quotes checked across {len(case_dirs)} case(s): "
          f"{len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
