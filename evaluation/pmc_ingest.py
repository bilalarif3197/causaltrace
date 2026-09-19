"""Harvest real ADR case reports from the PMC Open Access Subset.

Why this exists: CausalTrace's headline limitation is that its only reference
values are author-assigned on synthetic narratives. The challenge starter sheet
points at the fix -- many published ADR case reports state their *own* Naranjo
score or WHO-UMC category, so filtering the OA subset for those yields a
reference standard nobody on this project authored.

Access policy, taken seriously:
  * Only official interfaces are used -- E-utilities, the PMC ID converter, the
    OA service, and the BioC API. The PMC website is never scraped. Bulk
    scraping is prohibited and gets you IP-blocked.
  * Requests are throttled and backed off. NCBI allows 3 req/s without an API
    key and 10 with one (set NCBI_API_KEY). The BioC service is stricter in
    practice, so it gets its own slower budget.
  * Everything is cached on disk, so re-runs cost NCBI nothing.
  * `tool` and `email` identify the client on every E-utilities call, as NCBI
    requests. Override with NCBI_TOOL / NCBI_EMAIL.

Honesty policy, equally seriously: a regex-extracted score is a *candidate*,
not ground truth. Every record is written with `needs_review: true` and the
verbatim sentence the value was parsed from, so a human can confirm or reject
it before it is ever used as a reference. `--append` refuses to add unreviewed
records unless you pass --accept-unreviewed, and says why.

Usage:
    python evaluation/pmc_ingest.py --limit 40
    python evaluation/pmc_ingest.py --limit 40 --out candidates.json
    python evaluation/pmc_ingest.py --append --from candidates.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from services.naranjo import classify  # noqa: E402  (the published band mapping)

# NCBI serves a cross-signed chain whose self-signed root is absent from
# certifi, so the bundled CA store cannot build a path even though the chain is
# perfectly valid. The OS trust store handles it. Without this, every request
# fails with CERTIFICATE_VERIFY_FAILED that looks like a network outage.
try:
    import truststore

    truststore.inject_into_ssl()
    _TRUSTSTORE = True
except ImportError:  # pragma: no cover - environment dependent
    _TRUSTSTORE = False

HERE = Path(__file__).resolve().parent
CACHE = HERE / ".pmc_cache"
NARRATIVE_CACHE = CACHE / "narratives"
DATASET = HERE / "cases.json"

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
IDCONV = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
OA_SERVICE = "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi"
BIOC = "https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_json"

# Case reports in the OA subset that state their own causality assessment.
DEFAULT_QUERY = (
    '("Naranjo"[All Fields] OR "WHO-UMC"[All Fields] OR "WHO UMC"[All Fields]) '
    'AND "Case Reports"[Publication Type] '
    'AND "pubmed pmc open access"[Filter]'
)

# BioC section types that carry the actual patient narrative.
CASE_SECTIONS = {"CASE", "CASE_PRESENTATION", "METHODS", "RESULTS"}
NARRATIVE_STOP = {"DISCUSS", "CONCL", "REF", "ACK_FUND", "COMP_INT", "AUTH_CONT", "SUPPL"}

NARANJO_BANDS = ("definite", "probable", "possible", "doubtful")
UMC_CATEGORIES = ("certain", "probable", "possible", "unlikely", "conditional", "unassessable")


class Ncbi:
    """Throttled, cached, backing-off client for NCBI's official endpoints."""

    def __init__(self, *, cache: Path = CACHE, verbose: bool = True):
        self.api_key = os.environ.get("NCBI_API_KEY", "").strip()
        self.tool = os.environ.get("NCBI_TOOL", "causaltrace")
        self.email = os.environ.get("NCBI_EMAIL", "causaltrace@example.org")
        # 10 req/s with a key, 3 without. Halved for margin: being blocked
        # mid-hackathon costs far more than the extra seconds.
        self.min_interval = 0.12 if self.api_key else 0.40
        # BioC is a separate research service and rate-limits harder.
        self.bioc_interval = 1.2
        self._last: dict[str, float] = {}
        self.cache = cache
        self.cache.mkdir(parents=True, exist_ok=True)
        self.verbose = verbose
        self.stats = {"cached": 0, "fetched": 0, "retried": 0, "failed": 0}

    def _throttle(self, bucket: str, interval: float) -> None:
        gap = interval - (time.monotonic() - self._last.get(bucket, 0.0))
        if gap > 0:
            time.sleep(gap)

    def get(self, url: str, params: dict | None = None, *, bucket: str = "eutils") -> str:
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        key = self.cache / f"{hashlib.sha256(url.encode()).hexdigest()[:24]}.txt"
        if key.is_file():
            self.stats["cached"] += 1
            return key.read_text(encoding="utf-8")

        interval = self.bioc_interval if bucket == "bioc" else self.min_interval
        request = urllib.request.Request(url, headers={"User-Agent": f"{self.tool} (+{self.email})"})

        for attempt in range(6):
            self._throttle(bucket, interval)
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    body = response.read().decode("utf-8", "replace")
                self._last[bucket] = time.monotonic()
                self.stats["fetched"] += 1
                key.write_text(body, encoding="utf-8")
                return body
            except urllib.error.HTTPError as exc:
                self._last[bucket] = time.monotonic()
                if exc.code in (429, 500, 502, 503, 504) and attempt < 5:
                    self.stats["retried"] += 1
                    delay = min(30.0, (2**attempt) + random.random())
                    if self.verbose:
                        print(f"    HTTP {exc.code}; backing off {delay:.1f}s", file=sys.stderr)
                    time.sleep(delay)
                    continue
                self.stats["failed"] += 1
                raise
            except urllib.error.URLError as exc:
                self._last[bucket] = time.monotonic()
                if isinstance(getattr(exc, "reason", None), OSError) and "CERTIFICATE" in str(exc).upper():
                    raise SystemExit(
                        "TLS verification failed reaching NCBI.\n"
                        "NCBI serves a cross-signed chain that certifi cannot validate; the OS\n"
                        "trust store can. Install the helper and re-run:\n"
                        "    backend/.venv/bin/pip install truststore\n"
                        f"(truststore currently {'loaded' if _TRUSTSTORE else 'NOT installed'})"
                    ) from exc
                if attempt < 5:
                    self.stats["retried"] += 1
                    time.sleep(min(30.0, 2**attempt))
                    continue
                self.stats["failed"] += 1
                raise
        raise RuntimeError(f"gave up on {url}")

    def _common(self) -> dict[str, str]:
        params = {"tool": self.tool, "email": self.email}
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    def esearch(self, query: str, limit: int) -> list[str]:
        """PubMed search. Uses db=pubmed because [Publication Type] is honoured
        there -- in db=pmc it silently degrades to an All Fields match."""
        out: list[str] = []
        page = 200
        while len(out) < limit:
            body = self.get(
                f"{EUTILS}/esearch.fcgi",
                {
                    **self._common(),
                    "db": "pubmed",
                    "retmode": "json",
                    "sort": "relevance",
                    "retmax": str(min(page, limit - len(out))),
                    "retstart": str(len(out)),
                    "term": query,
                },
            )
            result = json.loads(body)["esearchresult"]
            ids = result.get("idlist", [])
            if not ids:
                break
            out.extend(ids)
            if len(out) >= int(result.get("count", 0)):
                break
        return out[:limit]

    def pmids_to_pmcids(self, pmids: list[str]) -> dict[str, str]:
        """Official ID converter, batched."""
        mapping: dict[str, str] = {}
        for i in range(0, len(pmids), 200):
            batch = pmids[i : i + 200]
            body = self.get(IDCONV, {**self._common(), "ids": ",".join(batch), "format": "json"})
            for record in json.loads(body).get("records", []):
                if record.get("pmcid") and not record.get("errmsg"):
                    mapping[record["pmid"]] = record["pmcid"]
        return mapping

    def license_for(self, pmcid: str) -> str | None:
        """License via efetch's <permissions> block.

        The OA subset is emphatically NOT uniformly CC-BY: plenty of articles
        are CC BY-NC-ND, and "No Derivatives" makes redistributing the text in
        a repository a real problem. (The older oa.fcgi service now 404s, so
        efetch is the route that works.)
        """
        numeric = pmcid.upper().removeprefix("PMC")
        try:
            body = self.get(f"{EUTILS}/efetch.fcgi", {**self._common(), "db": "pmc", "id": numeric})
        except Exception:
            return None
        block = re.search(r"<permissions>(.*?)</permissions>", body, re.S)
        if not block:
            return None
        url = re.search(r"(https?://creativecommons\.org/licenses/[a-z\-]+/[\d.]+)", block.group(1))
        if url:
            return url.group(1)
        text = " ".join(re.sub(r"<[^>]+>", " ", block.group(1)).split())
        return text[:120] or "unspecified"


    def bioc(self, pmcid: str) -> dict | None:
        """Full text via the BioC API. Requires the 'PMC' prefix."""
        if not pmcid.upper().startswith("PMC"):
            pmcid = f"PMC{pmcid}"
        body = self.get(f"{BIOC}/{pmcid}/unicode", bucket="bioc")
        if body.lstrip().startswith("[Error]"):
            return None  # not (yet) in the OA full-text service
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return None
        collection = data[0] if isinstance(data, list) else data
        docs = collection.get("documents") or []
        return docs[0] if docs else None


# ---------------------------------------------------------------------------
# Licensing
# ---------------------------------------------------------------------------


def license_is_redistributable(license_str: str | None) -> bool:
    """True only when the licence clearly permits redistributing the text.

    Conservative by design: anything unrecognised is treated as restricted, so
    the default never commits third-party text we lack clear rights to. Note
    that text *mining* is broadly permitted across the OA subset -- this is
    specifically about redistribution, which is what putting a narrative in a
    public git repository amounts to.
    """
    if not license_str:
        return False
    low = license_str.lower()
    if "-nd/" in low or "-nd " in low or low.endswith("-nd") or "no deriv" in low:
        return False
    return bool(re.search(r"/(by|by-sa|by-nc|by-nc-sa|zero|publicdomain)/", low) or "cc0" in low)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def passages(doc: dict) -> list[tuple[str, str]]:
    return [(str(p["infons"].get("section_type") or "").upper(), p.get("text", "")) for p in doc["passages"]]


def extract_narrative(doc: dict) -> str:
    """Pull the patient narrative, preferring explicit case sections.

    Falls back to everything between the introduction and the discussion, which
    is where case reports put the presentation when sections are untyped.
    """
    rows = passages(doc)
    cased = [t for s, t in rows if s in CASE_SECTIONS and len(t.split()) > 25]
    if cased:
        return "\n\n".join(cased).strip()

    collected, started = [], False
    for section, text in rows:
        if section in NARRATIVE_STOP:
            break
        if section in {"TITLE", "ABSTRACT"}:
            continue
        if section == "INTRO":
            started = True
            continue
        if started and len(text.split()) > 25:
            collected.append(text)
    return "\n\n".join(collected).strip()


#: Parenthetical scale legends, e.g. "(>9 = definite, 5-8 = probable, ...)".
#: These are full of digits that are NOT the case's score, so they are stripped
#: before searching. Real example encountered in the wild:
#:   "the Naranjo-score (>9 = highly probable, 5-8 = probable, 1-4 = possible
#:    and <=0 = doubtful) ... the score of 5 ... indicates a probable reaction"
_LEGEND = re.compile(r"\([^)]*?\d[^)]*?(?:probable|possible|doubtful|definite)[^)]*?\)", re.I)


def find_naranjo(text: str) -> tuple[int | None, str | None, str | None]:
    """Locate a self-reported Naranjo score and/or band, plus its sentence."""
    score: int | None = None
    band: str | None = None
    quote: str | None = None

    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if "naranjo" not in sentence.lower():
            continue
        # Search a legend-free copy so scale definitions cannot be mistaken for
        # the reported score; report the original sentence for human review.
        searchable = _LEGEND.sub(" ", sentence)

        # "score of 7", "score was 7", "score was found 7", "score = +5",
        # "scored 7", "7 points", "7/13"
        number = re.search(
            r"(?:scor\w*|total|index)\W{0,4}(?:of|was|were|is|found|calculated|as)?"
            r"\W{0,4}([+-]?\d{1,2})(?!\s*[-\u2013]\s*\d)\b"
            r"|\b([+-]?\d{1,2})\s*(?:points?|/\s*13)\b",
            searchable,
            re.I,
        )
        candidate = int(next(g for g in number.groups() if g is not None)) if number else None
        found_band = next((b for b in NARANJO_BANDS if b in searchable.lower()), None)

        if candidate is not None and -4 <= candidate <= 13 and score is None:
            score, quote = candidate, " ".join(sentence.split())
        if found_band and band is None:
            band = found_band.capitalize()
            quote = quote or " ".join(sentence.split())
    return score, band, quote


def find_umc(text: str) -> tuple[str | None, str | None]:
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        low = sentence.lower()
        if not re.search(r"\bwho[\s-]*umc\b|\bwho\b.{0,40}\bcausality\b|\buppsala\b", low):
            continue
        category = next((c for c in UMC_CATEGORIES if c in low), None)
        if category:
            pretty = {
                "conditional": "Conditional/Unclassified",
                "unassessable": "Unassessable/Unclassifiable",
            }.get(category, category.capitalize())
            return pretty, " ".join(sentence.split())
    return None, None


def guess_drug_and_event(doc: dict, narrative: str) -> tuple[str | None, str | None]:
    """Best-effort hints from the title. Deliberately weak -- a human confirms."""
    title = next((t for s, t in passages(doc) if s == "TITLE"), "")
    drug = event = None
    m = re.search(r"([A-Z][a-z]{3,}(?:mab|nib|pine|olol|azole|cillin|mycin|statin|pril|sartan|tide))", title)
    if m:
        drug = m.group(1)
    m = re.search(r"\b(induced|associated with|secondary to|due to)\s+([a-z][a-z\s\-]{4,40})", title, re.I)
    if m:
        event = m.group(2).strip().rstrip(":;,.")
    return drug, event


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def harvest(ncbi: Ncbi, query: str, limit: int, min_words: int) -> list[dict[str, Any]]:
    print(f"Searching PubMed (Case Reports, OA subset)...")
    pmids = ncbi.esearch(query, limit)
    print(f"  {len(pmids)} PMIDs")

    mapping = ncbi.pmids_to_pmcids(pmids)
    print(f"  {len(mapping)} resolved to PMCIDs")

    candidates: list[dict[str, Any]] = []
    skipped = {"no_fulltext": 0, "no_narrative": 0, "no_reference": 0}

    for n, (pmid, pmcid) in enumerate(mapping.items(), 1):
        print(f"  [{n}/{len(mapping)}] {pmcid}", end="", flush=True)
        try:
            doc = ncbi.bioc(pmcid)
        except Exception as exc:
            print(f"  fetch failed: {type(exc).__name__}")
            continue
        if doc is None:
            skipped["no_fulltext"] += 1
            print("  not in OA full text")
            continue

        full_text = "\n".join(t for _, t in passages(doc))
        narrative = extract_narrative(doc)
        if len(narrative.split()) < min_words:
            skipped["no_narrative"] += 1
            print(f"  narrative too short ({len(narrative.split())}w)")
            continue

        score, band, naranjo_quote = find_naranjo(full_text)
        umc, umc_quote = find_umc(full_text)
        if score is None and band is None and umc is None:
            skipped["no_reference"] += 1
            print("  no self-reported assessment")
            continue

        drug, event = guess_drug_and_event(doc, narrative)
        license_str = ncbi.license_for(pmcid)

        # Published papers do sometimes contradict themselves -- reporting a
        # score of 4 and calling it "probable" when 4 is Possible on the
        # published scale. A reference standard is only as good as its source,
        # so flag the disagreement rather than silently trusting either value.
        inconsistent = None
        if score is not None and band is not None and classify(score) != band:
            inconsistent = (
                f"Article reports score {score} and band '{band}', but {score} maps to "
                f"'{classify(score)}' on the published scale. Resolve before using."
            )

        # Narratives always go to the gitignored cache, never straight into the
        # committed dataset. Article text is third-party content and the OA
        # subset includes NC and ND licences.
        NARRATIVE_CACHE.mkdir(parents=True, exist_ok=True)
        (NARRATIVE_CACHE / f"{pmcid}.txt").write_text(narrative, encoding="utf-8")

        candidates.append(
            {
                "case_id": pmcid.lower(),
                "pmid": pmid,
                "pmcid": pmcid,
                "license": license_str,
                "license_redistributable": license_is_redistributable(license_str),
                "narrative": narrative,
                "suspected_drug": drug,
                "adverse_event": event,
                "reference_naranjo_score": score,
                "reference_naranjo_category": band,
                "reference_who_umc": umc,
                "reference_item_answers": None,
                "reference_source": "published",
                "needs_review": True,
                "internal_inconsistency": inconsistent,
                "parsed_from": {"naranjo": naranjo_quote, "who_umc": umc_quote},
                "notes": "Auto-harvested from the PMC OA subset. Score parsed by regex; "
                "confirm against `parsed_from` before using as a reference.",
            }
        )
        bits = [x for x in (f"naranjo={score}" if score is not None else None, band, umc) if x]
        flag = "  [!] self-inconsistent" if inconsistent else ""
        print(f"  CANDIDATE ({', '.join(bits)}){flag}")

    inconsistent_n = sum(1 for c in candidates if c["internal_inconsistency"])
    print(f"\n{len(candidates)} candidates; skipped {skipped}")
    if inconsistent_n:
        print(
            f"{inconsistent_n} article(s) report a score and a band that disagree with each "
            f"other.\nSee `internal_inconsistency`; published values are not automatically right."
        )
    restricted = sum(1 for c in candidates if not c["license_redistributable"])
    if restricted:
        print(f"{restricted} article(s) carry a licence that does not clearly permit redistribution.")
    print(f"http: {ncbi.stats}")
    return candidates


def append_to_dataset(candidates: list[dict], accept_unreviewed: bool) -> int:
    data = json.loads(DATASET.read_text())
    existing = {c["case_id"] for c in data["cases"]}
    added = 0
    blocked = 0
    withheld_text = 0

    for cand in candidates:
        if cand["case_id"] in existing:
            continue
        unreviewed = cand.get("needs_review", True)
        incomplete = not cand.get("suspected_drug") or not cand.get("adverse_event")
        if (unreviewed or incomplete) and not accept_unreviewed:
            blocked += 1
            continue

        record = {k: v for k, v in cand.items() if k != "needs_review"}
        # Only inline the text when the licence clearly permits redistribution.
        # Otherwise store the pointer; the loader reads from the local cache.
        if not cand.get("license_redistributable"):
            record["narrative"] = None
            record["narrative_source"] = "pmc_cache"
            withheld_text += 1
        data["cases"].append(record)
        added += 1

    if added:
        DATASET.write_text(json.dumps(data, indent=2) + "\n")
    print(f"Appended {added} case(s) to {DATASET.name}.")
    if withheld_text:
        print(
            f"  {withheld_text} narrative(s) were NOT inlined because the licence does not\n"
            f"  clearly permit redistribution (e.g. CC BY-NC-ND). The text stays in the\n"
            f"  gitignored cache at {NARRATIVE_CACHE.relative_to(HERE.parent)}/ and the loader\n"
            f"  reads it from there, so nothing third-party enters git history."
        )
    if blocked:
        print(
            f"Held back {blocked} record(s) pending human review, or missing a suspected drug /\n"
            f"adverse event. Confirm each against its `parsed_from` quote, set\n"
            f'"needs_review": false, fill in the drug and event, then re-run --append.\n'
            f"Use --accept-unreviewed to override (not recommended: an unchecked regex score\n"
            f"becomes your ground truth)."
        )
    return added


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=25, help="PubMed hits to consider (default 25)")
    ap.add_argument("--query", default=DEFAULT_QUERY)
    ap.add_argument("--min-words", type=int, default=120, help="minimum narrative length")
    ap.add_argument("--out", default=str(HERE / "pmc_candidates.json"))
    ap.add_argument("--append", action="store_true", help="merge candidates into cases.json")
    ap.add_argument("--from", dest="source", help="read candidates from this file instead of fetching")
    ap.add_argument("--accept-unreviewed", action="store_true")
    args = ap.parse_args()

    if args.source:
        candidates = json.loads(Path(args.source).read_text())
    else:
        if not _TRUSTSTORE:
            print(
                "note: truststore is not installed. NCBI's certificate chain often fails\n"
                "      certifi validation; install it if requests fail:\n"
                "          backend/.venv/bin/pip install truststore\n",
                file=sys.stderr,
            )
        candidates = harvest(Ncbi(), args.query, args.limit, args.min_words)
        Path(args.out).write_text(json.dumps(candidates, indent=2) + "\n")
        print(f"Wrote {args.out}")

    if args.append:
        append_to_dataset(candidates, args.accept_unreviewed)
    elif not args.source:
        print(
            "\nNext: review the candidates, confirm each score against its `parsed_from`\n"
            "quote, fill in suspected_drug / adverse_event, set needs_review to false,\n"
            f"then:  python evaluation/pmc_ingest.py --append --from {args.out}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
