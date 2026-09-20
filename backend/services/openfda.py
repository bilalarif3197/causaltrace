"""openFDA drug-label retrieval.

Exists to fix a specific dishonesty in this project. Naranjo item 1 asks
whether there are previous conclusive reports of the reaction, and until now the
model answered it from its own parametric memory -- no source, no quote, nothing
a reviewer could check. That is exactly the unverifiable assertion the rest of
the product is built to prevent.

This module retrieves the actual FDA label so the answer can cite text. The
retrieval is deterministic; a separate pass decides whether the label describes
the event, and its quote is then checked against the retrieved text, so the
claim is grounded the same way every other claim in the app is.

Two things this deliberately does NOT do:

  * It does not answer item 1. A reaction appearing on a label makes prior
    reports very likely -- labels are amended from post-marketing reports -- but
    a label is not itself a published case report. The reviewer decides.
  * It does not treat absence as a negative. A reaction missing from the label
    leaves item 1 UNKNOWN, never NO.

API notes: no key needed at this volume (240 requests/min per IP). Responses
are cached on disk so re-running a case costs nothing.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

try:  # NCBI/FDA chains validate against the OS store, not certifi
    import truststore

    truststore.inject_into_ssl()
except Exception:  # pragma: no cover - optional
    pass

BASE = "https://api.fda.gov/drug/label.json"
CACHE = Path(__file__).resolve().parent.parent / ".openfda_cache"
USER_AGENT = "CausalTrace/0.2 (research prototype; pharmacovigilance review)"

#: Label fields searched, in the order a reviewer would weight them.
SECTIONS = (
    "boxed_warning",
    "warnings_and_cautions",
    "adverse_reactions",
    "warnings",
    "precautions",
)

_last_call = 0.0
MIN_INTERVAL = 0.3  # be a good citizen even well under the published limit


class LabelUnavailable(RuntimeError):
    """No label could be retrieved. Not an error in the case, just no data."""


def _throttle() -> None:
    global _last_call
    wait = MIN_INTERVAL - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def _cache_path(key: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in key)[:120]
    return CACHE / f"{safe}.json"


def _get(url: str, cache_key: str) -> dict[str, Any]:
    path = _cache_path(cache_key)
    if path.is_file():
        return json.loads(path.read_text())

    _throttle()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            payload = {"results": [], "not_found": True}
        else:
            raise LabelUnavailable(f"openFDA returned HTTP {exc.code} for {cache_key}") from exc
    except urllib.error.URLError as exc:
        raise LabelUnavailable(f"Could not reach openFDA: {exc.reason}") from exc

    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return payload


#: Words that carry no product identity. A name made only of these is a class
#: label or a placeholder, not something with an FDA label.
GENERIC_WORDS = {
    "drug", "agent", "agents", "oral", "intravenous", "topical", "therapy", "class",
    "unknown", "suspected", "product", "medication", "medicine", "tablet", "capsule",
    "injection", "and", "the", "a", "an", "combination", "antibiotic", "antifungal",
    "antiviral", "nsaid", "inhibitor", "blocker", "analgesic",
}


def _clean(name: str) -> str:
    """Strip the parenthetical abbreviation reviewers habitually append."""
    if "(" in name:
        name = name.split("(")[0]
    return name.strip().strip(",;")


def _tokens(drug: str) -> list[str]:
    """Substantive ingredient tokens, used to search and to verify the match."""
    raw = _clean(drug).lower().replace("-", " ").replace("/", " ")
    words = [w.strip() for w in raw.split() if w.strip()]
    return [w for w in words if len(w) >= 4 and w not in GENERIC_WORDS]


def _queries(drug: str) -> list[tuple[str, str]]:
    """Search strategies, most specific first.

    There is deliberately no unconstrained full-text fallback. It used to match
    an ophthalmic product for oral TMP-SMX -- and a homeopathic one for the
    placeholder name "Drug A" -- then report that the reaction was absent from
    a label belonging to an entirely different medicine.
    """
    name = _clean(drug)
    tokens = _tokens(drug)
    out: list[tuple[str, str]] = []

    def add(kind: str, field: str, value: str) -> None:
        quoted = urllib.parse.quote(f'"{value}"')
        out.append((f"{kind}:{value}", f"search=openfda.{field}:{quoted}&limit=1"))

    for field, kind in (("generic_name", "generic"), ("brand_name", "brand"), ("substance_name", "substance")):
        add(kind, field, name)

    # Combination products are indexed in a fixed order that rarely matches how
    # a case report writes them ("trimethoprim-sulfamethoxazole" is listed as
    # "SULFAMETHOXAZOLE AND TRIMETHOPRIM"), so try both orders explicitly.
    if len(tokens) >= 2:
        for joined in (" and ".join(tokens), " and ".join(reversed(tokens))):
            add("generic", "generic_name", joined)
        for token in tokens:
            add("substance", "substance_name", token)

    seen: set[str] = set()
    return [(k, q) for k, q in out if not (q in seen or seen.add(q))]


def _confirms(record: dict[str, Any], tokens: list[str]) -> bool:
    """Does this label actually belong to the drug we asked about?

    openFDA will happily return a product whose name never appears in the
    query. Citing the wrong medicine's label is worse than finding nothing, so
    every hit must be confirmed against the label's own names.
    """
    openfda = record.get("openfda") or {}
    names = " ".join(
        " ".join(openfda.get(field) or [])
        for field in ("generic_name", "brand_name", "substance_name")
    ).lower()
    if not names:
        return False
    return any(token in names for token in tokens)


def fetch_label(drug: str) -> dict[str, Any]:
    """Return a confirmed matching label, or raise LabelUnavailable."""
    tokens = _tokens(drug)
    if not tokens:
        raise LabelUnavailable(
            f"'{drug}' is a drug class or placeholder rather than a specific product, so it "
            "has no FDA label. Naranjo item 1 must be answered from the literature instead."
        )

    attempts: list[str] = []
    rejected: list[str] = []
    for label, query in _queries(drug):
        payload = _get(f"{BASE}?{query}", label)
        results = payload.get("results") or []
        if not results:
            attempts.append(label)
            continue
        record = results[0]
        if not _confirms(record, tokens):
            openfda = record.get("openfda") or {}
            got = (openfda.get("generic_name") or openfda.get("brand_name") or ["unnamed"])[0]
            rejected.append(f"{label} -> {got}")
            continue
        record["_matched_by"] = label
        return record

    detail = f"Tried: {', '.join(attempts)}." if attempts else ""
    if rejected:
        detail += f" Rejected mismatched products: {'; '.join(rejected[:3])}."
    raise LabelUnavailable(
        f"No FDA label confirmed for '{drug}'. {detail} "
        "Non-US products, drug classes and investigational agents are not listed."
    )


def label_text(record: dict[str, Any]) -> tuple[str, str]:
    """Concatenate the safety-relevant sections into one quotable document.

    Returns (text, sections_included). Section headers are kept inline so a
    reviewer can see which part of the label a quote came from.
    """
    chunks: list[str] = []
    included: list[str] = []
    for section in SECTIONS:
        value = record.get(section)
        if not value:
            continue
        body = " ".join(value) if isinstance(value, list) else str(value)
        body = " ".join(body.split())
        if not body:
            continue
        chunks.append(f"[{section.upper().replace('_', ' ')}]\n{body}")
        included.append(section)
    if not chunks:
        raise LabelUnavailable("The retrieved label has no safety sections to quote.")
    return "\n\n".join(chunks), ", ".join(included)


def citation(record: dict[str, Any]) -> dict[str, Optional[str]]:
    openfda = record.get("openfda") or {}
    set_id = record.get("set_id") or (openfda.get("spl_set_id") or [None])[0]
    return {
        "label_id": record.get("id"),
        "set_id": set_id,
        "effective_time": record.get("effective_time"),
        "matched_by": record.get("_matched_by"),
        "brand_names": (openfda.get("brand_name") or [])[:4],
        "generic_names": (openfda.get("generic_name") or [])[:4],
        "manufacturer": (openfda.get("manufacturer_name") or [None])[0],
        "url": f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={set_id}" if set_id else None,
    }
