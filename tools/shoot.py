"""Screenshot the workspace so visual regressions can actually be seen.

Drives headless Chromium through every step of a case and writes a PNG per
screen, plus any console errors and failed requests. Without this the UI can
only be verified by type-checking, which catches nothing about layout.

Usage:
    python tools/shoot.py                 # reuse or seed a demo case
    python tools/shoot.py --fresh         # rebuild the seed case (spends tokens)
    python tools/shoot.py --step naranjo  # one screen only
    python tools/shoot.py --width 1440
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

OUT = ROOT / "tools" / "shots"
API = "http://localhost:8000"
APP = "http://localhost:3000"

STEPS = [
    "evidence",
    "timeline",
    "investigation",
    "hypotheses",
    "missing",
    "naranjo",
    "whoumc",
    "conclusion",
    "report",
]

SEED_TITLE = "[screenshot seed]"


def api(method: str, path: str, body=None):
    req = urllib.request.Request(
        API + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r) if r.status != 204 else None


def find_seed() -> str | None:
    for case in api("GET", "/api/cases"):
        if case["title"].startswith(SEED_TITLE):
            return case["id"]
    return None


def seed_case(fresh: bool) -> str:
    """A case with every stage populated and partially reviewed.

    Deliberately left in a MIXED review state -- some accepted, one modified,
    one rejected, some still pending -- because a screenshot of an all-pending
    or all-accepted case hides most of the states the UI has to render.
    """
    existing = find_seed()
    if existing and not fresh:
        print(f"reusing seed case {existing}")
        return existing
    if existing:
        api("DELETE", f"/api/cases/{existing}")

    demo = next(c for c in api("GET", "/api/demo-cases") if c["case_id"] == "tmpsmx-dili-004")
    env = api(
        "POST",
        "/api/cases",
        {
            "narrative": demo["narrative"],
            "suspected_drug": demo["suspected_drug"],
            "adverse_event": demo["adverse_event"],
            "title": f"{SEED_TITLE} {demo['title']}",
            "indication": demo["indication"],
            "age": demo["age"],
            "sex": demo["sex"],
            "concomitant_medications": demo["concomitant_medications"],
            "comorbidities": demo["comorbidities"],
        },
    )
    cid = env["case"]["id"]
    print(f"seeding {cid} (this runs live AI, ~40s)")

    for stage in ("facts", "timeline", "dimensions", "hypotheses", "naranjo", "missing", "who_umc"):
        t0 = time.perf_counter()
        api("POST", f"/api/cases/{cid}/suggest/{stage}")
        print(f"  {stage:<12} {time.perf_counter()-t0:4.1f}s")

    env = api("POST", f"/api/cases/{cid}/review/bulk", {"entity_type": "fact", "status": "REVIEWER_ACCEPTED"})
    facts = env["case"]["facts"]
    api("PATCH", f"/api/cases/{cid}/review/fact/{facts[1]['id']}",
        {"status": "REVIEWER_MODIFIED", "value": "160/800 mg twice daily (corrected)", "note": "dose restated"})
    api("PATCH", f"/api/cases/{cid}/review/fact/{facts[2]['id']}", {"status": "REVIEWER_REJECTED"})

    api("POST", f"/api/cases/{cid}/review/bulk", {"entity_type": "event", "status": "REVIEWER_ACCEPTED"})
    api("POST", f"/api/cases/{cid}/review/bulk", {"entity_type": "dimension", "status": "REVIEWER_ACCEPTED"})
    api("POST", f"/api/cases/{cid}/review/bulk", {"entity_type": "naranjo", "status": "REVIEWER_ACCEPTED"})

    env = api("GET", f"/api/cases/{cid}")
    for h in env["case"]["hypotheses"][:4]:
        api("PATCH", f"/api/cases/{cid}/review/hypothesis/{h['id']}",
            {"value": "Moderately supported" if h["is_suspected_drug"] else "Weakly supported"})

    env = api("GET", f"/api/cases/{cid}")
    if env["case"]["missing_evidence"]:
        api("PATCH", f"/api/cases/{cid}/review/missing/{env['case']['missing_evidence'][0]['id']}",
            {"value": "UNAVAILABLE"})
    api("PATCH", f"/api/cases/{cid}/review/who_umc/current", {"value": "Possible"})
    api("POST", f"/api/cases/{cid}/suggest/rationale")

    env = api("GET", f"/api/cases/{cid}")
    api("PUT", f"/api/cases/{cid}/conclusion", {
        "final_assessment": "Possible",
        "primary_cause_hypothesis_id": env["case"]["hypotheses"][0]["id"],
        "reviewer_rationale": env["case"]["conclusion"]["ai_draft_rationale"],
    })
    return cid


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fresh", action="store_true", help="rebuild the seed case")
    ap.add_argument("--step", help="capture only this step")
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=1000)
    ap.add_argument("--home", action="store_true", help="capture the landing page only")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.png"):
        old.unlink()

    cid = None if args.home else seed_case(args.fresh)
    problems: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": args.width, "height": args.height})

        page.on("console", lambda m: problems.append(f"console.{m.type}: {m.text}") if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
        page.on("requestfailed", lambda r: problems.append(f"requestfailed: {r.url} {r.failure}"))

        def shoot(name: str, url: str, wait_for: str | None = None):
            page.goto(url, wait_until="networkidle")
            if wait_for:
                try:
                    page.wait_for_selector(wait_for, timeout=8000)
                except Exception:
                    problems.append(f"{name}: selector {wait_for!r} never appeared")
            page.wait_for_timeout(700)
            path = OUT / f"{name}.png"
            page.screenshot(path=str(path), full_page=True)
            box = page.evaluate(
                "() => ({w: document.documentElement.scrollWidth, h: document.documentElement.scrollHeight,"
                " overflow: document.documentElement.scrollWidth > window.innerWidth})"
            )
            flag = "  <-- HORIZONTAL OVERFLOW" if box["overflow"] else ""
            print(f"  {name:<16} {box['w']}x{box['h']}{flag}")
            if box["overflow"]:
                problems.append(f"{name}: page scrolls horizontally ({box['w']}px wide)")

        print("\ncapturing:")
        shoot("00-home", APP + "/", "text=New case")

        if cid:
            for step in STEPS if not args.step else [args.step]:
                page.goto(f"{APP}/case/{cid}", wait_until="networkidle")
                page.wait_for_timeout(500)
                label = {
                    "evidence": "Evidence review",
                    "timeline": "Clinical timeline",
                    "investigation": "Investigation",
                    "hypotheses": "Competing causes",
                    "missing": "Missing evidence",
                    "naranjo": "Naranjo framework",
                    "whoumc": "WHO-UMC",
                    "conclusion": "Reviewer conclusion",
                    "report": "Case report",
                }[step]
                try:
                    page.click(f"button:has-text('{label}')", timeout=5000)
                except Exception:
                    problems.append(f"{step}: could not click step '{label}'")
                    continue
                page.wait_for_timeout(900)
                path = OUT / f"{STEPS.index(step)+1:02d}-{step}.png"
                page.screenshot(path=str(path), full_page=True)
                box = page.evaluate(
                    "() => ({w: document.documentElement.scrollWidth, h: document.documentElement.scrollHeight,"
                    " overflow: document.documentElement.scrollWidth > window.innerWidth})"
                )
                flag = "  <-- HORIZONTAL OVERFLOW" if box["overflow"] else ""
                print(f"  {step:<16} {box['w']}x{box['h']}{flag}")
                if box["overflow"]:
                    problems.append(f"{step}: page scrolls horizontally ({box['w']}px)")

        browser.close()

    print(f"\nwrote {len(list(OUT.glob('*.png')))} screenshots to {OUT.relative_to(ROOT)}/")
    if problems:
        print(f"\n{len(problems)} problem(s) detected:")
        for p_ in dict.fromkeys(problems):
            print(f"  - {p_[:160]}")
    else:
        print("\nno console errors, page errors or overflow detected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
