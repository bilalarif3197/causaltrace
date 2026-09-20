"""Case workspace operations.

Everything a reviewer or a suggestion run does to a case goes through here, so
there is exactly one place that (a) records an audit entry and (b) persists.

Invariants enforced in this module:
  * A suggestion run never touches an existing reviewer decision. Re-running
    extraction adds new candidates; it does not resurrect rejected ones or
    overwrite accepted values.
  * Reviewer actions never modify `ai`. `apply_review` writes only reviewer
    fields, which is what keeps the audit trail meaningful.
  * The Naranjo total is recomputed from reviewer answers on every read, so it
    cannot go stale relative to the document.
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional

from schemas.review import (
    AiSuggestion,
    Answer,
    AssessmentLevel,
    CaseDocument,
    CaseEnvelope,
    CONFIRMED_STATUSES,
    DateKind,
    Fact,
    FactSection,
    Hypothesis,
    LabelEvidence,
    MissingEvidenceItem,
    MissingEvidenceStatus,
    Origin,
    PatientContext,
    ReviewerStatus,
    TimelineEntry,
    Verdict,
    utcnow,
)
from services import store, suggest
from services.assessment import (
    blank_naranjo_items,
    compute_stats,
    score_framework,
)

DISCLAIMER = (
    "CausalTrace is an AI-assisted pharmacovigilance workspace. It organises evidence and "
    "suggests interpretations; the reviewer makes every clinically meaningful judgment. It "
    "does not establish medical causation, is not a medical device, and is not a clinical "
    "decision tool."
)

#: Stages that read only the narrative, so they may be computed concurrently.
#: `missing` and `rationale` are excluded deliberately -- both read
#: reviewer-confirmed evidence and would see an empty case if run too early.
PARALLEL_STAGES = ("facts", "timeline", "dimensions", "hypotheses", "naranjo", "who_umc")

SUGGEST_STAGES = (
    "facts",
    "timeline",
    "dimensions",
    "hypotheses",
    "missing",
    "naranjo",
    "who_umc",
    "rationale",
)

ENTITY_TYPES = ("fact", "event", "dimension", "hypothesis", "hypothesis_evidence", "naranjo", "missing", "who_umc")


class WorkspaceError(RuntimeError):
    """Client-correctable problem (unknown entity, bad stage, ...)."""


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


def envelope(doc: CaseDocument) -> CaseEnvelope:
    """Document plus everything derived from it, recomputed fresh."""
    framework = score_framework(doc.naranjo) if doc.naranjo else None
    return CaseEnvelope(
        case=doc,
        stats=compute_stats(doc),
        framework=framework,
        stage=store.stage_of(doc),
        disclaimer=DISCLAIMER,
    )


def framework_summary(doc: CaseDocument) -> str:
    """Plain-text framework state, for the rationale drafter."""
    lines: list[str] = []
    if doc.naranjo:
        result = score_framework(doc.naranjo)
        lines.append(
            f"Naranjo (from reviewer answers): {result.total_score} -> {result.classification}. "
            f"{result.unknown_count} of 10 items UNKNOWN; possible range if resolved "
            f"{result.score_floor} to {result.score_ceiling}"
            + ("" if result.classification_is_stable else " (classification NOT stable).")
        )
    if doc.who_umc and doc.who_umc.reviewer_classification:
        lines.append(f"WHO-UMC (reviewer-selected): {doc.who_umc.reviewer_classification}")
    return "\n".join(lines) or "(No framework results yet.)"


# ---------------------------------------------------------------------------
# Case creation
# ---------------------------------------------------------------------------


def create_case(
    *,
    narrative: str,
    suspected_drug: str,
    adverse_event: str,
    title: str = "",
    patient: PatientContext | None = None,
    demo_case_id: str | None = None,
    client=None,
) -> CaseDocument:
    doc = CaseDocument(
        id=store.new_case_id(),
        title=title or f"{suspected_drug} / {adverse_event}",
        narrative=narrative.strip(),
        suspected_drug=suspected_drug.strip(),
        adverse_event=adverse_event.strip(),
        patient=patient or PatientContext(),
        demo_case_id=demo_case_id,
        naranjo=blank_naranjo_items(),
        # Record the provider up front. Otherwise a brand-new case reports the
        # default "mock" in the UI until the first stage happens to finish,
        # which reads as though a live run were offline.
        mode=getattr(client, "mode", "mock") if client else "mock",
        model_used=getattr(client, "name", None) if client else None,
    )
    store.save_case(doc)
    store.log(
        doc.id,
        actor=Origin.REVIEWER,
        action="CASE_CREATED",
        entity_type="case",
        entity_id=doc.id,
        summary=f"Case opened for {doc.suspected_drug} / {doc.adverse_event}",
    )
    return doc


# ---------------------------------------------------------------------------
# Suggestion runs
# ---------------------------------------------------------------------------


def _compute(client, doc: CaseDocument, stage: str):
    """Call the model for one stage. Must NOT mutate `doc`.

    Kept side-effect free so several stages can be computed concurrently
    against the same document; the merge that follows is single-threaded.
    """
    if stage == "facts":
        return suggest.verify_facts(client, doc, suggest.suggest_facts(client, doc))
    if stage == "timeline":
        return suggest.suggest_timeline(client, doc)
    if stage == "dimensions":
        return suggest.suggest_dimensions(client, doc)
    if stage == "hypotheses":
        return suggest.suggest_hypotheses(client, doc)
    if stage == "missing":
        return suggest.suggest_missing_evidence(client, doc)
    if stage == "naranjo":
        return suggest.suggest_naranjo(client, doc)
    if stage == "who_umc":
        return suggest.suggest_who_umc(client, doc)
    if stage == "rationale":
        return suggest.draft_rationale(client, doc, framework_summary(doc))
    raise WorkspaceError(f"Unknown stage '{stage}'. Expected one of {', '.join(SUGGEST_STAGES)}.")


def _merge(doc: CaseDocument, stage: str, result) -> str:
    """Fold a computed result into the document. Single-threaded, mutating."""
    note = ""

    if stage == "facts":
        facts = result
        # Re-running must not clobber review work: keep every fact the reviewer
        # has already touched, and only add genuinely new candidates.
        reviewed = [f for f in doc.facts if f.reviewer_status is not ReviewerStatus.AI_SUGGESTED]
        seen = {(f.field, (f.ai.value if f.ai else None)) for f in reviewed}
        fresh = [f for f in facts if (f.field, f.ai.value if f.ai else None) not in seen]
        doc.facts = reviewed + fresh
        unsupported = sum(1 for f in fresh if f.ai and f.ai.verification is not Verdict.SUPPORTED)
        note = f"Extracted {len(fresh)} candidate fact(s)"
        if unsupported:
            note += f"; {unsupported} flagged by verification and marked Needs Review"
        if reviewed:
            note += f"; kept {len(reviewed)} already-reviewed item(s)"

    elif stage == "timeline":
        events = result
        kept = [e for e in doc.timeline if e.reviewer_status is not ReviewerStatus.AI_SUGGESTED]
        labels = {e.label for e in kept}
        fresh = [e for e in events if e.label not in labels]
        doc.timeline = _renumber(kept + fresh)
        note = f"Suggested {len(fresh)} timeline event(s)"

    elif stage == "dimensions":
        incoming = result
        existing = {d.id: d for d in doc.dimensions}
        merged = []
        for question in incoming:
            prior = existing.get(question.id)
            # Preserve the reviewer's answer; refresh only the AI half.
            if prior and prior.reviewer_status is not ReviewerStatus.AI_SUGGESTED:
                prior.ai = question.ai
                merged.append(prior)
            else:
                merged.append(question)
        doc.dimensions = merged
        note = f"Answered {len(incoming)} investigation question(s)"

    elif stage == "hypotheses":
        incoming = result
        assessed = [h for h in doc.hypotheses if h.reviewer_assessment or h.origin is Origin.REVIEWER]
        labels = {h.label.strip().lower() for h in assessed}
        fresh = [h for h in incoming if h.label.strip().lower() not in labels]
        doc.hypotheses = assessed + fresh
        note = f"Suggested {len(fresh)} competing hypothes{'is' if len(fresh) == 1 else 'es'}"

    elif stage == "missing":
        items = result
        touched = [m for m in doc.missing_evidence if m.status is not MissingEvidenceStatus.OPEN]
        prompts = {m.prompt.strip().lower() for m in touched}
        fresh = [m for m in items if m.prompt.strip().lower() not in prompts]
        doc.missing_evidence = touched + fresh
        note = f"Identified {len(fresh)} information gap(s)"

    elif stage == "naranjo":
        if not doc.naranjo:
            doc.naranjo = blank_naranjo_items()
        suggestions = result
        changed = 0
        for item in doc.naranjo:
            suggestion = suggestions.get(item.number)
            if not suggestion:
                continue
            item.ai = suggestion
            try:
                item.ai_answer = Answer(suggestion.value or "UNKNOWN")
            except ValueError:
                item.ai_answer = Answer.UNKNOWN
            # Never overwrite an answer the reviewer has given.
            if item.reviewer_status in (ReviewerStatus.AI_SUGGESTED, ReviewerStatus.NEEDS_REVIEW):
                item.reviewer_status = ReviewerStatus.AI_SUGGESTED
                changed += 1
        note = f"Suggested answers for {changed} unreviewed Naranjo item(s)"

    elif stage == "who_umc":
        incoming = result
        if doc.who_umc and doc.who_umc.reviewer_classification:
            doc.who_umc.ai_classification = incoming.ai_classification
            doc.who_umc.ai_reasoning = incoming.ai_reasoning
            doc.who_umc.ai_major_uncertainty = incoming.ai_major_uncertainty
            doc.who_umc.key_evidence = incoming.key_evidence
        else:
            doc.who_umc = incoming
        note = f"Suggested WHO-UMC category: {incoming.ai_classification}"

    elif stage == "rationale":
        text = result
        doc.conclusion.ai_draft_rationale = text
        if doc.conclusion.rationale_status is ReviewerStatus.AI_SUGGESTED:
            doc.conclusion.reviewer_rationale = text
        note = "Drafted a rationale from reviewer-confirmed evidence"

    return note


def _finalise(doc: CaseDocument, client, stages: list[str]) -> None:
    for stage in stages:
        if stage not in doc.stages_run:
            doc.stages_run.append(stage)
    doc.model_used = getattr(client, "name", None)
    doc.mode = getattr(client, "mode", "mock")


def run_suggest(client, doc: CaseDocument, stage: str) -> tuple[CaseDocument, str]:
    """Run one AI stage. Returns the document and a human-readable note."""
    if stage not in SUGGEST_STAGES:
        raise WorkspaceError(f"Unknown stage '{stage}'. Expected one of {', '.join(SUGGEST_STAGES)}.")

    note = _merge(doc, stage, _compute(client, doc, stage))
    _finalise(doc, client, [stage])

    store.save_case(doc)
    store.log(
        doc.id,
        actor=Origin.AI,
        action=f"SUGGEST_{stage.upper()}",
        entity_type=stage,
        summary=note,
        after={"model": doc.model_used, "mode": doc.mode},
    )
    return doc, note


def run_suggest_batch(
    client, doc: CaseDocument, stages: list[str]
) -> tuple[CaseDocument, list[str], dict[str, str]]:
    """Compute several stages concurrently, then merge them one at a time.

    Only PARALLEL_STAGES are permitted. `missing` and `rationale` read
    reviewer-confirmed evidence, so running them alongside extraction would
    show them an empty case; they stay sequential by construction rather than
    by convention.

    Concurrency is confined to `_compute`, which does not touch the document.
    Merging happens on this thread in a fixed order, so the result does not
    depend on which model call returned first, and the case is saved once.
    """
    unknown = [s for s in stages if s not in PARALLEL_STAGES]
    if unknown:
        raise WorkspaceError(
            f"Cannot run {', '.join(unknown)} in parallel. "
            f"Batchable stages are: {', '.join(PARALLEL_STAGES)}."
        )

    results: dict[str, object] = {}
    errors: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=len(stages) or 1) as pool:
        futures = {pool.submit(_compute, client, doc, s): s for s in stages}
        for future in as_completed(futures):
            stage = futures[future]
            try:
                results[stage] = future.result()
            except Exception as exc:  # noqa: BLE001 - reported per stage
                errors[stage] = f"{type(exc).__name__}: {exc}"

    notes: list[str] = []
    # Merge in the caller's order, not completion order, so the outcome is
    # deterministic regardless of network timing.
    for stage in stages:
        if stage in results:
            notes.append(_merge(doc, stage, results[stage]))

    _finalise(doc, client, [s for s in stages if s in results])
    store.save_case(doc)
    store.log(
        doc.id,
        actor=Origin.AI,
        action="SUGGEST_BATCH",
        entity_type="batch",
        summary="; ".join(notes) or "no stages completed",
        after={"stages": list(results), "failed": errors, "model": doc.model_used},
    )
    return doc, notes, errors


def lookup_label_evidence(client, doc: CaseDocument) -> tuple[CaseDocument, str]:
    """Retrieve the FDA label and record what it says about this reaction.

    Deliberately does not touch any Naranjo answer. Item 1 stays the reviewer's
    to answer; this only puts citable text in front of them where previously
    there was only the model's recollection.
    """
    from services import openfda
    from services.spans import locate_span

    drug, event = doc.suspected_drug, doc.adverse_event

    try:
        record = openfda.fetch_label(drug)
        text, sections = openfda.label_text(record)
    except openfda.LabelUnavailable as exc:
        doc.label_evidence = LabelEvidence(
            queried_drug=drug,
            adverse_event=event,
            label_found=False,
            unavailable_reason=str(exc),
        )
        note = f"No FDA label available for '{drug}'"
        store.save_case(doc)
        store.log(
            doc.id,
            actor=Origin.AI,
            action="LABEL_LOOKUP",
            entity_type="label_evidence",
            summary=note,
        )
        return doc, note

    raw = suggest.match_label_evidence(client, drug, event, text)
    quote = raw.get("quote") or None
    mentions = raw.get("mentions_event")

    # Same grounding gate as everywhere else: a quote that is not in the
    # retrieved label is a fabricated citation, so it is discarded and the
    # finding downgraded to undetermined rather than shown as evidence.
    span = locate_span(text, quote) if quote else None
    if quote and (span is None or not span.located):
        quote, span = None, None
        mentions = None
        raw["reasoning"] = (
            (raw.get("reasoning") or "")
            + " [Quote discarded: it does not appear in the retrieved label text.]"
        ).strip()

    doc.label_evidence = LabelEvidence(
        queried_drug=drug,
        adverse_event=event,
        label_found=True,
        mentions_event=mentions if isinstance(mentions, bool) else None,
        quote=quote,
        span=span,
        section=raw.get("section"),
        reasoning=raw.get("reasoning", ""),
        label_text=text,
        sections_included=sections,
        citation=openfda.citation(record),
    )

    if doc.label_evidence.mentions_event is True:
        note = f"FDA label for '{drug}' describes this reaction"
    elif doc.label_evidence.mentions_event is False:
        note = f"FDA label for '{drug}' does not list this reaction (item 1 stays UNKNOWN)"
    else:
        note = f"Retrieved the FDA label for '{drug}'; whether it covers this reaction is unclear"

    if "label" not in doc.stages_run:
        doc.stages_run.append("label")
    store.save_case(doc)
    store.log(
        doc.id,
        actor=Origin.AI,
        action="LABEL_LOOKUP",
        entity_type="label_evidence",
        summary=note,
        after={"mentions_event": doc.label_evidence.mentions_event, **doc.label_evidence.citation},
    )
    return doc, note


def _renumber(events: list[TimelineEntry]) -> list[TimelineEntry]:
    events = sorted(events, key=lambda e: e.order_index)
    for i, event in enumerate(events, start=1):
        event.order_index = i
    return events


# ---------------------------------------------------------------------------
# Reviewer actions
# ---------------------------------------------------------------------------


def _describe(status: ReviewerStatus) -> str:
    return {
        ReviewerStatus.ACCEPTED: "accepted",
        ReviewerStatus.MODIFIED: "modified",
        ReviewerStatus.REJECTED: "rejected",
        ReviewerStatus.UNKNOWN: "marked unknown",
        ReviewerStatus.NEEDS_REVIEW: "flagged for review",
        ReviewerStatus.AI_SUGGESTED: "reset to AI suggestion",
    }[status]


def apply_review(
    doc: CaseDocument,
    entity_type: str,
    entity_id: str,
    *,
    status: Optional[ReviewerStatus] = None,
    value: Optional[str] = None,
    note: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
) -> CaseDocument:
    """Record a reviewer decision on one entity, and audit it."""
    extra = extra or {}

    if entity_type == "fact":
        target = doc.find_fact(entity_id)
        if not target:
            raise WorkspaceError(f"No fact '{entity_id}'.")
        before = {"status": target.reviewer_status.value, "value": target.confirmed_value}
        target.apply_review(status or target.reviewer_status, value, note)
        target.origin = target.origin
        after = {"status": target.reviewer_status.value, "value": target.confirmed_value}
        summary = f"Fact '{target.label}' {_describe(target.reviewer_status)}"

    elif entity_type == "event":
        target = doc.find_event(entity_id)
        if not target:
            raise WorkspaceError(f"No timeline event '{entity_id}'.")
        before = target.model_dump(mode="json", include={"label", "order_index", "date_kind", "display_date", "reviewer_status"})
        if status:
            target.apply_review(status, value, note)
        for field in ("label", "display_date", "relative_text", "date_value", "actor"):
            if field in extra:
                setattr(target, field, extra[field])
        if "date_kind" in extra:
            target.date_kind = DateKind(extra["date_kind"])
            target.timing_uncertain = target.date_kind in (DateKind.APPROXIMATE, DateKind.UNKNOWN)
        if "timing_uncertain" in extra:
            target.timing_uncertain = bool(extra["timing_uncertain"])
        if "order_index" in extra:
            target.order_index = int(extra["order_index"])
            doc.timeline = _renumber(doc.timeline)
        if any(k in extra for k in ("label", "display_date", "date_kind", "order_index")):
            if target.reviewer_status in (ReviewerStatus.AI_SUGGESTED, ReviewerStatus.NEEDS_REVIEW):
                target.apply_review(ReviewerStatus.MODIFIED, target.label, note)
        after = target.model_dump(mode="json", include={"label", "order_index", "date_kind", "display_date", "reviewer_status"})
        summary = f"Timeline event '{target.label}' {_describe(target.reviewer_status)}"

    elif entity_type == "dimension":
        target = doc.find_dimension(entity_id)
        if not target:
            raise WorkspaceError(f"No investigation question '{entity_id}'.")
        before = {"status": target.reviewer_status.value, "value": target.confirmed_value}
        target.apply_review(status or target.reviewer_status, value, note)
        after = {"status": target.reviewer_status.value, "value": target.confirmed_value}
        summary = f"{target.dimension.value}: '{target.question}' {_describe(target.reviewer_status)}"

    elif entity_type == "hypothesis":
        target = doc.find_hypothesis(entity_id)
        if not target:
            raise WorkspaceError(f"No hypothesis '{entity_id}'.")
        before = {
            "reviewer_assessment": target.reviewer_assessment.value if target.reviewer_assessment else None,
            "status": target.reviewer_status.value,
        }
        if value is not None:
            try:
                target.reviewer_assessment = AssessmentLevel(value)
            except ValueError as exc:
                raise WorkspaceError(
                    f"'{value}' is not a valid assessment. Expected one of: "
                    + ", ".join(level.value for level in AssessmentLevel)
                ) from exc
        if status:
            target.reviewer_status = status
        elif target.reviewer_assessment:
            target.reviewer_status = (
                ReviewerStatus.ACCEPTED
                if target.reviewer_assessment == target.ai_assessment
                else ReviewerStatus.MODIFIED
            )
        if note is not None:
            target.reviewer_note = note
        target.reviewed_at = utcnow()
        after = {
            "reviewer_assessment": target.reviewer_assessment.value if target.reviewer_assessment else None,
            "status": target.reviewer_status.value,
        }
        summary = (
            f"Hypothesis '{target.label}' assessed as "
            f"{target.reviewer_assessment.value if target.reviewer_assessment else 'unassessed'}"
        )

    elif entity_type == "hypothesis_evidence":
        target = doc.find_hypothesis_evidence(entity_id)
        if not target:
            raise WorkspaceError(f"No hypothesis evidence '{entity_id}'.")
        before = {"status": target.reviewer_status.value}
        target.apply_review(status or target.reviewer_status, value, note)
        after = {"status": target.reviewer_status.value}
        summary = f"Evidence '{target.statement[:60]}' {_describe(target.reviewer_status)}"

    elif entity_type == "naranjo":
        try:
            number = int(entity_id)
        except ValueError as exc:
            raise WorkspaceError("Naranjo entity id must be an item number 1-10.") from exc
        target = next((i for i in doc.naranjo if i.number == number), None)
        if not target:
            raise WorkspaceError(f"No Naranjo item {number}.")
        before = {"answer": target.reviewer_answer.value, "status": target.reviewer_status.value, "score": target.score}
        if value is not None:
            try:
                target.reviewer_answer = Answer(value)
            except ValueError as exc:
                raise WorkspaceError(f"'{value}' is not YES, NO or UNKNOWN.") from exc
        if status:
            target.reviewer_status = status
        else:
            target.reviewer_status = (
                ReviewerStatus.ACCEPTED
                if target.ai_answer and target.reviewer_answer == target.ai_answer
                else ReviewerStatus.MODIFIED
            )
        if note is not None:
            target.reviewer_note = note
        target.reviewed_at = utcnow()
        score_framework(doc.naranjo)  # instant deterministic recompute
        after = {"answer": target.reviewer_answer.value, "status": target.reviewer_status.value, "score": target.score}
        summary = f"Naranjo item {number} answered {target.reviewer_answer.value} ({target.score:+d})"

    elif entity_type == "missing":
        target = doc.find_missing(entity_id)
        if not target:
            raise WorkspaceError(f"No missing-evidence item '{entity_id}'.")
        before = {"status": target.status.value}
        if value is not None:
            try:
                target.status = MissingEvidenceStatus(value)
            except ValueError as exc:
                raise WorkspaceError(
                    f"'{value}' is not a valid status. Expected one of: "
                    + ", ".join(s.value for s in MissingEvidenceStatus)
                ) from exc
        if note is not None:
            target.reviewer_note = note
        target.reviewed_at = utcnow()
        after = {"status": target.status.value}
        summary = f"Information gap '{target.prompt[:60]}' marked {target.status.value}"

    elif entity_type == "who_umc":
        if not doc.who_umc:
            raise WorkspaceError("WHO-UMC has not been suggested for this case yet.")
        before = {
            "reviewer_classification": doc.who_umc.reviewer_classification,
            "status": doc.who_umc.reviewer_status.value,
        }
        if value is not None:
            doc.who_umc.reviewer_classification = value
        if status:
            doc.who_umc.reviewer_status = status
        elif doc.who_umc.reviewer_classification:
            doc.who_umc.reviewer_status = (
                ReviewerStatus.ACCEPTED
                if doc.who_umc.reviewer_classification == doc.who_umc.ai_classification
                else ReviewerStatus.MODIFIED
            )
        if note is not None:
            doc.who_umc.reviewer_note = note
        doc.who_umc.reviewed_at = utcnow()
        after = {
            "reviewer_classification": doc.who_umc.reviewer_classification,
            "status": doc.who_umc.reviewer_status.value,
        }
        summary = f"WHO-UMC category set to {doc.who_umc.reviewer_classification}"

    else:
        raise WorkspaceError(
            f"Unknown entity type '{entity_type}'. Expected one of {', '.join(ENTITY_TYPES)}."
        )

    store.save_case(doc)
    store.log(
        doc.id,
        actor=Origin.REVIEWER,
        action="REVIEW",
        entity_type=entity_type,
        entity_id=entity_id,
        summary=summary,
        before=before,
        after=after,
    )
    return doc


def bulk_review(doc: CaseDocument, entity_type: str, status: ReviewerStatus, section: str | None = None) -> tuple[CaseDocument, int]:
    """Apply one decision to every pending item of a type.

    Exists because a reviewer should not have to click twenty times to accept
    an extraction that is simply correct. Only *pending* items are touched --
    a bulk action can never silently reverse an earlier explicit decision.
    """
    count = 0
    if entity_type == "fact":
        for fact in doc.facts:
            if fact.reviewer_status not in (ReviewerStatus.AI_SUGGESTED, ReviewerStatus.NEEDS_REVIEW):
                continue
            if section and fact.section.value != section:
                continue
            fact.apply_review(status)
            count += 1
    elif entity_type == "event":
        for event in doc.timeline:
            if event.reviewer_status in (ReviewerStatus.AI_SUGGESTED, ReviewerStatus.NEEDS_REVIEW):
                event.apply_review(status)
                count += 1
    elif entity_type == "dimension":
        for question in doc.dimensions:
            if question.reviewer_status in (ReviewerStatus.AI_SUGGESTED, ReviewerStatus.NEEDS_REVIEW):
                question.apply_review(status)
                count += 1
    elif entity_type == "naranjo":
        for item in doc.naranjo:
            if item.reviewer_status in (ReviewerStatus.AI_SUGGESTED, ReviewerStatus.NEEDS_REVIEW):
                if status is ReviewerStatus.ACCEPTED and item.ai_answer:
                    item.reviewer_answer = item.ai_answer
                item.reviewer_status = status
                item.reviewed_at = utcnow()
                count += 1
        score_framework(doc.naranjo)
    else:
        raise WorkspaceError(f"Bulk review is not supported for '{entity_type}'.")

    store.save_case(doc)
    store.log(
        doc.id,
        actor=Origin.REVIEWER,
        action="BULK_REVIEW",
        entity_type=entity_type,
        summary=f"{count} pending {entity_type}(s) {_describe(status)}"
        + (f" in section {section}" if section else ""),
    )
    return doc, count


# ---------------------------------------------------------------------------
# Manual additions -- the reviewer must be able to add what the AI missed
# ---------------------------------------------------------------------------


def add_fact(doc: CaseDocument, *, field: str, value: str, note: str | None = None) -> tuple[CaseDocument, Fact]:
    if field not in suggest.FIELD_LABELS:
        raise WorkspaceError(f"Unknown field '{field}'.")
    fact = Fact(
        id=f"fact-{uuid.uuid4().hex[:8]}",
        section=suggest.FIELD_SECTION[field],
        field=field,
        label=suggest.FIELD_LABELS[field],
        ai=None,
        reviewer_status=ReviewerStatus.MODIFIED,
        reviewer_value=value,
        reviewer_note=note,
        origin=Origin.REVIEWER,
        reviewed_at=utcnow(),
    )
    doc.facts.append(fact)
    store.save_case(doc)
    store.log(
        doc.id,
        actor=Origin.REVIEWER,
        action="ADD_FACT",
        entity_type="fact",
        entity_id=fact.id,
        summary=f"Reviewer added fact '{fact.label}': {value}",
        after={"value": value},
    )
    return doc, fact


def add_event(
    doc: CaseDocument,
    *,
    label: str,
    order_index: int | None = None,
    date_kind: str = "UNKNOWN",
    display_date: str | None = None,
    relative_text: str | None = None,
    category: str = "OTHER",
    actor: str | None = None,
) -> tuple[CaseDocument, TimelineEntry]:
    kind = DateKind(date_kind)
    event = TimelineEntry(
        id=f"evt-{uuid.uuid4().hex[:8]}",
        label=label,
        category=category,
        order_index=order_index if order_index is not None else len(doc.timeline) + 1,
        date_kind=kind,
        display_date=display_date,
        relative_text=relative_text,
        actor=actor,
        timing_uncertain=kind in (DateKind.APPROXIMATE, DateKind.UNKNOWN),
        ai=None,
        reviewer_status=ReviewerStatus.MODIFIED,
        reviewer_value=label,
        origin=Origin.REVIEWER,
        reviewed_at=utcnow(),
    )
    doc.timeline = _renumber(doc.timeline + [event])
    store.save_case(doc)
    store.log(
        doc.id,
        actor=Origin.REVIEWER,
        action="ADD_EVENT",
        entity_type="event",
        entity_id=event.id,
        summary=f"Reviewer added timeline event '{label}'",
    )
    return doc, event


def delete_event(doc: CaseDocument, event_id: str) -> CaseDocument:
    event = doc.find_event(event_id)
    if not event:
        raise WorkspaceError(f"No timeline event '{event_id}'.")
    doc.timeline = _renumber([e for e in doc.timeline if e.id != event_id])
    store.save_case(doc)
    store.log(
        doc.id,
        actor=Origin.REVIEWER,
        action="DELETE_EVENT",
        entity_type="event",
        entity_id=event_id,
        summary=f"Reviewer removed timeline event '{event.label}'",
        before={"label": event.label},
    )
    return doc


def add_hypothesis(doc: CaseDocument, *, label: str, kind: str = "OTHER") -> tuple[CaseDocument, Hypothesis]:
    hypothesis = Hypothesis(
        id=f"hyp-{uuid.uuid4().hex[:8]}",
        label=label,
        kind=kind,
        ai_assessment=None,
        reviewer_status=ReviewerStatus.MODIFIED,
        origin=Origin.REVIEWER,
        reviewed_at=utcnow(),
    )
    doc.hypotheses.append(hypothesis)
    store.save_case(doc)
    store.log(
        doc.id,
        actor=Origin.REVIEWER,
        action="ADD_HYPOTHESIS",
        entity_type="hypothesis",
        entity_id=hypothesis.id,
        summary=f"Reviewer added hypothesis '{label}'",
    )
    return doc, hypothesis


def add_missing_item(doc: CaseDocument, *, prompt: str, why: str = "") -> tuple[CaseDocument, MissingEvidenceItem]:
    item = MissingEvidenceItem(
        id=f"miss-{uuid.uuid4().hex[:8]}",
        prompt=prompt,
        why_it_matters=why,
        origin=Origin.REVIEWER,
        reviewed_at=utcnow(),
    )
    doc.missing_evidence.append(item)
    store.save_case(doc)
    store.log(
        doc.id,
        actor=Origin.REVIEWER,
        action="ADD_MISSING",
        entity_type="missing",
        entity_id=item.id,
        summary=f"Reviewer noted an information gap: '{prompt[:60]}'",
    )
    return doc, item


# ---------------------------------------------------------------------------
# Conclusion
# ---------------------------------------------------------------------------


def set_conclusion(
    doc: CaseDocument,
    *,
    final_assessment: str | None = None,
    primary_cause_hypothesis_id: str | None = None,
    reviewer_rationale: str | None = None,
    signed_off: bool | None = None,
) -> CaseDocument:
    before = doc.conclusion.model_dump(mode="json")

    if final_assessment is not None:
        doc.conclusion.final_assessment = final_assessment
    if primary_cause_hypothesis_id is not None:
        if primary_cause_hypothesis_id and not doc.find_hypothesis(primary_cause_hypothesis_id):
            raise WorkspaceError(f"No hypothesis '{primary_cause_hypothesis_id}'.")
        doc.conclusion.primary_cause_hypothesis_id = primary_cause_hypothesis_id or None
    if reviewer_rationale is not None:
        doc.conclusion.reviewer_rationale = reviewer_rationale
        draft = doc.conclusion.ai_draft_rationale
        doc.conclusion.rationale_status = (
            ReviewerStatus.ACCEPTED
            if draft and reviewer_rationale.strip() == draft.strip()
            else ReviewerStatus.MODIFIED
        )
    if signed_off is not None:
        doc.conclusion.signed_off = signed_off

    doc.conclusion.decided_at = utcnow()
    store.save_case(doc)
    store.log(
        doc.id,
        actor=Origin.REVIEWER,
        action="SIGN_OFF" if doc.conclusion.signed_off else "CONCLUSION",
        entity_type="conclusion",
        summary=(
            f"Reviewer conclusion: {doc.conclusion.final_assessment or 'not set'}"
            + (" (signed off)" if doc.conclusion.signed_off else "")
        ),
        before=before,
        after=doc.conclusion.model_dump(mode="json"),
    )
    return doc
