"""Resolve model-quoted evidence back to character offsets in the narrative.

This is the first and cheapest anti-hallucination layer in the pipeline. If a
model cites a quote that does not actually occur in the source text, we learn
that here -- deterministically, with no extra LLM call -- and the claim is
demoted rather than displayed.

Three matching strategies, tried in order:
  exact       verbatim substring
  normalized  whitespace/quote-punctuation collapsed (models re-wrap text)
  fuzzy       difflib best window, accepted only above FUZZY_THRESHOLD

Anything below threshold is `unlocatable`, which the pipeline treats as a
hallucinated citation.
"""

from __future__ import annotations

import difflib
import re

from schemas.models import SourceSpan

# A fuzzy match below this ratio is not trustworthy enough to show a user as a
# verbatim source highlight.
FUZZY_THRESHOLD = 0.82

_WS = re.compile(r"\s+")
# Models routinely normalise curly quotes/dashes when echoing source text.
_PUNCT_MAP = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-"})


def _canon(text: str) -> str:
    return _WS.sub(" ", text.translate(_PUNCT_MAP)).strip().lower()


def _build_canon_index(narrative: str) -> tuple[str, list[int]]:
    """Canonical form of the narrative plus a map back to original offsets.

    index[i] is the offset in `narrative` of the character that produced
    canonical character i.
    """
    out: list[str] = []
    index: list[int] = []
    prev_space = True  # leading whitespace is stripped
    for i, ch in enumerate(narrative.translate(_PUNCT_MAP)):
        if ch.isspace():
            if prev_space:
                continue
            out.append(" ")
            index.append(i)
            prev_space = True
        else:
            out.append(ch.lower())
            index.append(i)
            prev_space = False
    # Mirror .strip() on the trailing side
    while out and out[-1] == " ":
        out.pop()
        index.pop()
    return "".join(out), index


def locate_span(narrative: str, quote: str | None) -> SourceSpan | None:
    """Locate `quote` within `narrative`, returning a SourceSpan or None.

    Returns None only when there is no quote at all. A quote that cannot be
    found yields a SourceSpan with locator='unlocatable' so the caller can
    count it.
    """
    if not quote or not quote.strip():
        return None

    # 1. Exact
    idx = narrative.find(quote)
    if idx != -1:
        return SourceSpan(text=quote, start=idx, end=idx + len(quote), locator="exact", match_ratio=1.0)

    canon_narr, index = _build_canon_index(narrative)
    canon_quote = _canon(quote)
    if not canon_quote:
        return SourceSpan(text=quote, locator="unlocatable", match_ratio=0.0)

    # 2. Normalized
    idx = canon_narr.find(canon_quote)
    if idx != -1:
        start = index[idx]
        end = index[min(idx + len(canon_quote), len(index)) - 1] + 1
        return SourceSpan(
            text=narrative[start:end], start=start, end=end, locator="normalized", match_ratio=1.0
        )

    # 3. Fuzzy -- slide a same-length window and keep the best ratio.
    best_ratio, best_at = 0.0, -1
    n, q = len(canon_narr), len(canon_quote)
    if q and n >= q:
        # Coarse stride first, then refine locally: full per-character scan is
        # O(n*q) and needlessly slow on long case reports.
        stride = max(1, q // 4)
        matcher = difflib.SequenceMatcher(autojunk=False, b=canon_quote)
        for start in range(0, n - q + 1, stride):
            matcher.set_seq1(canon_narr[start : start + q])
            r = matcher.quick_ratio()
            if r > best_ratio:
                best_ratio, best_at = r, start
        if best_at >= 0:
            lo = max(0, best_at - stride)
            hi = min(n - q, best_at + stride)
            for start in range(lo, hi + 1):
                matcher.set_seq1(canon_narr[start : start + q])
                r = matcher.ratio()
                if r > best_ratio:
                    best_ratio, best_at = r, start

    if best_at >= 0 and best_ratio >= FUZZY_THRESHOLD:
        start = index[best_at]
        end = index[min(best_at + q, len(index)) - 1] + 1
        return SourceSpan(
            text=narrative[start:end], start=start, end=end, locator="fuzzy", match_ratio=round(best_ratio, 3)
        )

    return SourceSpan(text=quote, locator="unlocatable", match_ratio=round(best_ratio, 3))
