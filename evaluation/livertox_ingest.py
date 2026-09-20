"""Harvest curated DILI case narratives from LiverTox (NCBI Bookshelf).

Why this matters more than the PMC harvester: **LiverTox text is not copyright
protected.** NCBI states "The text of LiverTox is not copyright protected and
its general use is encouraged." The PMC Open Access Subset, by contrast,
includes CC BY-NC-ND articles, which is why `pmc_ingest.py` can only store a
PMCID pointer and keeps narratives in a gitignored cache. LiverTox narratives
can live in the repository where a reviewer -- or a judge -- can actually read
them.

Access rules, which are explicit and enforced by NCBI:

    "Crawlers and other automated processes may NOT be used to systematically
    retrieve content from the Bookshelf web site, and bulk downloading of books
    is prohibited. Bookshelf does have two auxiliary services, the NLM LitArch
    OAI service and NLM LitArch FTP service, that may be used to download
    certain content in bulk."

So: E-utilities to find sections, then the OAI-PMH service for full text. The
website is never touched. `efetch` does not serve Bookshelf body text at all,
which is what forces the OAI route.

The FTP tarball (`litarch/29/31/livertox_NBK547852.tar.gz`) is the alternative
for a full mirror, but it is 189 MB of mostly images and PDFs when all that is
wanted here is a few dozen XML chapters.

Same discipline as the PMC harvester: throttled, cached, and every record is a
candidate marked `needs_review` rather than a reference standard.

Usage:
    python evaluation/livertox_ingest.py --limit 20
    python evaluation/livertox_ingest.py --limit 20 --out evaluation/livertox_cases.json
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

try:
    import truststore

    truststore.inject_into_ssl()
except Exception:  # pragma: no cover
    print("note: install truststore if NCBI TLS validation fails", file=sys.stderr)

HERE = Path(__file__).resolve().parent
CACHE = HERE / ".livertox_cache"
DEFAULT_OUT = HERE / "livertox_cases.json"

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
OAI = "https://api.ncbi.nlm.nih.gov/lit/oai/books/"
UA = "CausalTrace/0.2 (research prototype; pharmacovigilance causality assessment)"

MIN_INTERVAL = 0.4  # under the 3/sec unauthenticated E-utilities limit
_last = 0.0

LICENCE = (
    "LiverTox text is not copyright protected (NCBI/NIDDK); general use is encouraged. "
    "Retrieved via E-utilities and the NLM LitArch OAI service, never by crawling the "
    "Bookshelf website."
)

#: LiverTox grades each drug's hepatotoxicity likelihood A-E in its own text.
LIKELIHOOD_RE = re.compile(
    r"[Ll]ikelihood\s+score:?\s*([A-E])(?:\[|\s|\(|,|\.|$)", re.M
)
RUCAM_RE = re.compile(r"\bRUCAM\b[^.]{0,80}?(\d{1,2})\b", re.I)
NARANJO_RE = re.compile(r"\bNaranjo\b[^.]{0,80}?(\d{1,2})\b", re.I)
R_VALUE_RE = re.compile(r"\bR\s*(?:value|ratio)\s*(?:of|=|was)?\s*([\d.]+)", re.I)


def throttle() -> None:
    global _last
    wait = MIN_INTERVAL - (time.monotonic() - _last)
    if wait > 0:
        time.sleep(wait)
    _last = time.monotonic()


def cached_get(url: str, key: str) -> str:
    path = CACHE / f"{key}.cache"
    if path.is_file():
        return path.read_text(encoding="utf-8")
    throttle()
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read().decode("utf-8", "replace")
            break
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503) and attempt < 3:
                time.sleep(2**attempt)
                continue
            raise
    else:  # pragma: no cover
        raise RuntimeError(f"gave up on {key}")
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return body


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def find_case_sections(limit: int) -> list[str]:
    """UIDs of LiverTox sections titled CASE REPORT."""
    query = urllib.parse.urlencode(
        {
            "db": "books",
            "term": 'livertox[book] AND "CASE REPORT"[title]',
            "retmax": limit,
            "retmode": "json",
        }
    )
    body = cached_get(EUTILS + "esearch.fcgi?" + query, f"esearch-{limit}")
    return json.loads(body)["esearchresult"].get("idlist", [])


def summarise(uids: list[str]) -> dict[str, dict]:
    query = urllib.parse.urlencode({"db": "books", "id": ",".join(uids), "retmode": "json"})
    body = cached_get(EUTILS + "esummary.fcgi?" + query, f"esummary-{len(uids)}-{uids[0]}")
    return json.loads(body)["result"]


def drug_from_summary(summary: dict) -> Optional[str]:
    """The chapter title is the drug name."""
    match = re.search(r'type="chapter"[^>]*><Title>([^<]+)</Title>', summary.get("bookinfo", ""))
    return match.group(1).strip() if match else None


def fetch_chapter_xml(accession: str) -> str:
    number = accession.replace("NBK", "")
    url = OAI + "?" + urllib.parse.urlencode(
        {
            "verb": "GetRecord",
            "identifier": f"oai:books.ncbi.nlm.nih.gov:{number}",
            "metadataPrefix": "nbk_ftext",
        }
    )
    return cached_get(url, f"oai-{accession}")


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def strip_markup(fragment: str) -> str:
    """XML fragment to clean prose.

    Comments must go first: LiverTox chapters carry editorial notes such as
    'The in-text citation "1" is not in the reference list. Please correct...'
    which would otherwise be spliced into the middle of a case narrative.
    """
    fragment = re.sub(r"<!--.*?-->", " ", fragment, flags=re.S)
    fragment = re.sub(r"<(table-wrap|fig|ref-list|graphic)\b.*?</\1>", " ", fragment, flags=re.S | re.I)
    # Editorial notes survive as plain text in some chapters; drop them too.
    fragment = re.sub(
        r"The in-text citation[^.]*\.\s*Please[^.]*\.\s*(-->)?", " ", fragment, flags=re.I
    )
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    # Decode entities properly rather than patching the few that show up:
    # a hand-rolled version left "R &lt; 2.0" in the extracted pattern field.
    fragment = fragment.replace("&#x000a0;", " ")
    fragment = html.unescape(fragment)
    return " ".join(fragment.split())


def extract_section(xml: str, title: str) -> Optional[str]:
    """Return the raw XML of the first <sec> whose <title> starts with `title`."""
    pattern = re.compile(
        r"<sec\b[^>]*>\s*<title>\s*" + re.escape(title) + r".*?</sec>", re.S | re.I
    )
    match = pattern.search(xml)
    return match.group(0) if match else None


ROW_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.S | re.I)
CELL_RE = re.compile(r"<(th|td)\b[^>]*>(.*?)</\1>", re.S | re.I)


def parse_key_value_table(fragment: str) -> dict[str, str]:
    """LiverTox 'Key Points' is a two-column table, not prose.

    It carries exactly the fields this project extracts -- pattern, severity,
    latency, recovery, other medications -- so it is structured reference data
    and must not be stripped as boilerplate, which is what an earlier version
    of this parser did.
    """
    out: dict[str, str] = {}
    for row in ROW_RE.findall(fragment):
        cells = [strip_markup(body) for _, body in CELL_RE.findall(row)]
        cells = [c for c in cells if c]
        if len(cells) >= 2:
            key = cells[0].rstrip(":").strip().lower().replace(" ", "_")
            if key:
                out[key] = " ".join(cells[1:]).strip()
    return out


def split_case_report(section_xml: str) -> dict[str, Any]:
    """A LiverTox CASE REPORT is a narrative plus labelled subsections."""
    out: dict[str, Any] = {}

    for label, field in (
        ("Key Points", "key_points"),
        ("Laboratory Values", "laboratory_values"),
        ("Comment", "comment"),
    ):
        sub = extract_section(section_xml, label)
        if not sub:
            out[field] = {} if field == "key_points" else ""
            continue
        # Tables become key/value pairs; prose stays prose.
        if "<table" in sub.lower():
            parsed = parse_key_value_table(sub)
            out[field] = parsed if field == "key_points" else " | ".join(
                f"{k}: {v}" for k, v in parsed.items()
            )
        else:
            out[field] = strip_markup(sub) if field != "key_points" else {}
        section_xml = section_xml.replace(sub, " ")

    narrative = strip_markup(section_xml)
    narrative = re.sub(r"^CASE REPORT\s*", "", narrative, flags=re.I).strip()
    out["narrative"] = narrative
    return out


def parse_chapter(xml: str, drug: str, accession: str) -> Optional[dict[str, Any]]:
    section = extract_section(xml, "CASE REPORT")
    if not section:
        return None
    parts = split_case_report(section)
    narrative = parts.get("narrative", "")
    if len(narrative) < 250:
        return None  # a stub, not a usable case

    hepatotox = extract_section(xml, "Hepatotoxicity")
    hepatotox_text = strip_markup(hepatotox) if hepatotox else ""
    whole = strip_markup(xml)

    key_points: dict[str, str] = parts.get("key_points") or {}
    # key_points is a dict now; flatten it before any regex search.
    flat_points = " ".join(f"{k}: {v}" for k, v in key_points.items())
    searchable = " ".join([narrative, parts.get("comment", "") or "", flat_points])

    likelihood = LIKELIHOOD_RE.search(whole)
    rucam = RUCAM_RE.search(searchable)
    naranjo = NARANJO_RE.search(searchable)
    r_value = R_VALUE_RE.search(searchable)

    return {
        "source": "livertox",
        "accession": accession,
        "url": f"https://www.ncbi.nlm.nih.gov/books/{accession}/",
        "drug": drug,
        "narrative": narrative,
        "key_points": parts.get("key_points") or {},
        "laboratory_values": parts.get("laboratory_values", ""),
        "comment": parts.get("comment", ""),
        # LiverTox grades the DRUG's likelihood of causing DILI, not this case.
        "drug_likelihood_score": likelihood.group(1) if likelihood else None,
        "reported_rucam": int(rucam.group(1)) if rucam else None,
        "reported_naranjo": int(naranjo.group(1)) if naranjo else None,
        "r_value": float(r_value.group(1)) if r_value else None,
        "hepatotoxicity_excerpt": hepatotox_text[:600],
        "licence": LICENCE,
        # Nothing here is a reference standard until a human confirms it.
        "needs_review": True,
        "review_notes": (
            "Confirm the suspected drug, the adverse event, and whether any causality value "
            "quoted above belongs to THIS case rather than to the drug in general. "
            "drug_likelihood_score grades the drug, not the case, and must not be used as a "
            "per-case causality reference."
        ),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=20, help="how many CASE REPORT sections to try")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    print("=" * 78)
    print("LiverTox case harvester (NCBI Bookshelf, OAI-PMH)")
    print("=" * 78)
    print(LICENCE)
    print()

    uids = find_case_sections(args.limit)
    print(f"found {len(uids)} CASE REPORT section(s)\n")
    if not uids:
        return 1

    summaries = summarise(uids)
    kept: list[dict] = []
    skipped = 0

    for i, uid in enumerate(uids, start=1):
        summary = summaries.get(uid) or {}
        accession = summary.get("chapteraccessionid")
        drug = drug_from_summary(summary)
        if not accession or not drug:
            skipped += 1
            continue
        print(f"[{i:>2}/{len(uids)}] {drug:<28} {accession} ...", end="", flush=True)
        try:
            xml = fetch_chapter_xml(accession)
            record = parse_chapter(xml, drug, accession)
        except Exception as exc:  # noqa: BLE001
            print(f" failed: {type(exc).__name__}: {exc}")
            skipped += 1
            continue
        if not record:
            print(" no usable case narrative")
            skipped += 1
            continue

        flags = []
        if record["drug_likelihood_score"]:
            flags.append(f"likelihood={record['drug_likelihood_score']}")
        if record["reported_rucam"]:
            flags.append(f"RUCAM={record['reported_rucam']}")
        if record["reported_naranjo"]:
            flags.append(f"Naranjo={record['reported_naranjo']}")
        if record["r_value"]:
            flags.append(f"R={record['r_value']}")
        print(f" {len(record['narrative'])} chars  {' '.join(flags) or '(no causality value)'}")
        kept.append(record)

    out = Path(args.out)
    out.write_text(
        json.dumps(
            {
                "dataset": {
                    "name": "LiverTox curated DILI case narratives",
                    "source": "NCBI Bookshelf / NIDDK LiverTox",
                    "retrieved_via": "E-utilities esearch + esummary, NLM LitArch OAI-PMH GetRecord",
                    "licence": LICENCE,
                    "caveat": (
                        "LiverTox case reports are illustrative and often condensed, and the "
                        "likelihood score grades the drug rather than the individual case. "
                        "Every record needs human confirmation before use as a reference."
                    ),
                },
                "cases": kept,
            },
            indent=2,
        )
        + "\n"
    )

    print(f"\nkept {len(kept)}, skipped {skipped}")
    print(f"wrote {out.relative_to(HERE.parent)}")
    print(
        "\nEvery record is marked needs_review. LiverTox grades the DRUG's likelihood of "
        "causing liver injury, which is not a causality assessment of the individual case, "
        "so it must not be used as a per-case reference."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
