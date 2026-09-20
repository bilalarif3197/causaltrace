"""Small, constrained AI functions that propose -- never decide.

Each function here produces suggestions in review-model shape: an immutable
`AiSuggestion` plus a reviewer slot that starts empty. Nothing in this module
writes a reviewer decision, and nothing reads one except the two functions that
are explicitly built on confirmed evidence (`suggest_missing_evidence` and
`draft_rationale`).

There is deliberately no single agent prompt. Extraction is asked to be
comprehensive, verification is asked only to falsify, and the rationale drafter
is shown nothing but what the reviewer already signed off on. Giving one prompt
several of those jobs is what produces confident, unfalsifiable prose.
"""

from __future__ import annotations

import uuid
from typing import Any

from schemas.review import (
    AiSuggestion,
    Answer,
    AssessmentLevel,
    CaseDocument,
    DateKind,
    Dimension,
    DIMENSION_QUESTIONS,
    DimensionQuestion,
    EvidenceValence,
    Fact,
    FactSection,
    Hypothesis,
    HypothesisEvidence,
    MissingEvidenceItem,
    Origin,
    ReviewerStatus,
    SECTION_FIELDS,
    TimelineEntry,
    Verdict,
    WhoUmcReview,
)
from services import who_umc as who_umc_service
from services.assessment import confirmed_evidence_digest
from services.naranjo import answer_items as naranjo_answer_items
from services.spans import locate_span

FIELD_LABELS = {key: label for fields in SECTION_FIELDS.values() for key, label in fields}
FIELD_SECTION = {
    key: section for section, fields in SECTION_FIELDS.items() for key, _ in fields
}


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _case_header(doc: CaseDocument) -> str:
    bits = [f"Suspected drug: {doc.suspected_drug}", f"Adverse event: {doc.adverse_event}"]
    p = doc.patient
    for label, value in (
        ("Indication", p.indication),
        ("Age", p.age),
        ("Sex", p.sex),
        ("Concomitant medications", p.concomitant_medications),
        ("Comorbidities", p.comorbidities),
    ):
        if value:
            bits.append(f"{label}: {value}")
    return "\n".join(bits)


def _suggestion(narrative: str, value: Any, quote: str | None, confidence: float, rationale: str = "") -> AiSuggestion:
    span = locate_span(narrative, quote)
    suggestion = AiSuggestion(
        value=None if value is None else str(value),
        evidence_text=quote,
        span=span,
        confidence=float(confidence or 0.0),
        rationale=rationale,
    )
    # Deterministic grounding gate. A quote that is not in the source is a
    # fabricated citation, and the reviewer must see that before anything else.
    if quote and (span is None or not span.located):
        suggestion.verification = Verdict.NOT_SUPPORTED
        suggestion.verification_reason = "Cited text does not appear in the narrative."
    return suggestion


# ---------------------------------------------------------------------------
# extract_case_facts()
# ---------------------------------------------------------------------------

FACTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string", "enum": list(FIELD_LABELS)},
                    "value": {"type": ["string", "null"]},
                    "evidence_text": {
                        "type": ["string", "null"],
                        "description": "Verbatim span copied from the narrative, or null.",
                    },
                    "confidence": {"type": "number"},
                },
            },
        }
    },
}

FACTS_SYSTEM = """You extract candidate clinical facts from an adverse drug event case narrative
so that a pharmacovigilance reviewer can check them.

You are an extractor, not a judge. Do not assess causality and do not score anything.

Rules:
- `evidence_text` must be copied character-for-character from the narrative. Never
  paraphrase, reformat or correct a quote.
- The `value` must state a FACT, never an interpretation. The field name already carries
  the category, so do not restate it.
    Wrong: "Pneumonia is a potential alternative cause."
    Right: "Community-acquired pneumonia on chest radiograph."
- Emit a SEPARATE entry per concomitant medication, per infection, per comorbidity and
  per lab abnormality. Do not bundle several into one value.
- Omit a field entirely if the narrative does not mention it. Do not emit placeholder
  entries -- the workspace already shows the reviewer which fields were never filled.
- Never infer from clinical knowledge what is typical for the drug or condition."""


def suggest_facts(client, doc: CaseDocument) -> list[Fact]:
    raw = client.complete_json(
        stage="facts",
        system=FACTS_SYSTEM,
        user=(
            f"{_case_header(doc)}\n\nNARRATIVE:\n\"\"\"\n{doc.narrative}\n\"\"\"\n\n"
            "Extract every candidate fact you can support with a verbatim quote."
        ),
        schema=FACTS_SCHEMA,
        schema_name="case_facts",
        case_id=doc.demo_case_id,
    )

    facts: list[Fact] = []
    for row in raw.get("facts", []):
        field = row.get("field")
        if field not in FIELD_LABELS:
            continue
        facts.append(
            Fact(
                id=_uid("fact"),
                section=FIELD_SECTION[field],
                field=field,
                label=FIELD_LABELS[field],
                ai=_suggestion(doc.narrative, row.get("value"), row.get("evidence_text"), row.get("confidence", 0.0)),
                reviewer_status=ReviewerStatus.AI_SUGGESTED,
                origin=Origin.AI,
            )
        )
    return facts


# ---------------------------------------------------------------------------
# verify_evidence_support()
# ---------------------------------------------------------------------------

VERIFY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "verdict": {
                        "type": "string",
                        "enum": ["SUPPORTED", "PARTIALLY_SUPPORTED", "NOT_SUPPORTED"],
                    },
                    "reason": {"type": "string"},
                },
            },
        }
    },
}

VERIFY_SYSTEM = """You audit extracted claims against the text that was cited for them.

For each item decide only whether the quote establishes that specific claim.

- SUPPORTED: the quote directly states it.
- PARTIALLY_SUPPORTED: the quote supports part of it, or supports the topic but not the
  specific value (a date, a dose, a severity) the claim asserts.
- NOT_SUPPORTED: the quote does not state it, concerns something else, or says the
  opposite. A classic example: a claim that a cause was "excluded", cited to text saying
  the relevant test was never performed. Not tested is not excluded.

Audit, do not assist. Do not repair a weak claim, and use only the narrative and the
quote -- never outside clinical knowledge. A claim that is clinically plausible but not
established by its quote is NOT_SUPPORTED."""


def verify_facts(client, doc: CaseDocument, facts: list[Fact]) -> list[Fact]:
    """Second pass over facts whose quote was actually located in the source."""
    targets = [f for f in facts if f.ai and f.ai.grounded and f.ai.verification is None]
    if not targets:
        return facts

    block = "\n\n".join(
        f'id: {f.id}\nfield: {f.label}\nclaim: {f.ai.value}\ncited evidence: "{f.ai.evidence_text}"'
        for f in targets
    )
    raw = client.complete_json(
        stage="verification",
        system=VERIFY_SYSTEM,
        user=f'NARRATIVE:\n"""\n{doc.narrative}\n"""\n\nAudit each claim below.\n\n{block}',
        schema=VERIFY_SCHEMA,
        schema_name="verify_facts",
        case_id=doc.demo_case_id,
    )
    by_id = {r.get("id"): r for r in raw.get("verdicts", [])}

    for fact in targets:
        row = by_id.get(fact.id)
        if not row:
            fact.ai.verification = Verdict.PARTIALLY_SUPPORTED
            fact.ai.verification_reason = "Verifier returned no verdict for this claim."
            continue
        fact.ai.verification = Verdict(row.get("verdict", "PARTIALLY_SUPPORTED"))
        fact.ai.verification_reason = row.get("reason", "")
        # Never auto-promote or auto-delete. Flag it and let the reviewer decide.
        if fact.ai.verification is not Verdict.SUPPORTED:
            fact.reviewer_status = ReviewerStatus.NEEDS_REVIEW
    return facts


# ---------------------------------------------------------------------------
# extract_timeline_events()
# ---------------------------------------------------------------------------

TIMELINE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "category": {
                        "type": "string",
                        "enum": [
                            "DRUG_START", "DRUG_STOP", "DOSE_CHANGE", "EVENT_ONSET", "LAB",
                            "INFECTION", "DIAGNOSIS", "RECHALLENGE", "RECOVERY", "OTHER",
                        ],
                    },
                    "order": {"type": "integer"},
                    "date_kind": {"type": "string", "enum": ["EXACT", "APPROXIMATE", "RELATIVE", "UNKNOWN"]},
                    "date_value": {"type": ["string", "null"]},
                    "display_date": {"type": ["string", "null"]},
                    "relative_text": {"type": ["string", "null"]},
                    "actor": {"type": ["string", "null"]},
                    "evidence_text": {"type": ["string", "null"]},
                },
            },
        }
    },
}

TIMELINE_SYSTEM = """You reconstruct a clinical timeline from an adverse drug event narrative.

Rules:
- NEVER invent a date, and never infer a year that is not written down. "3 January" with
  no year is date_kind EXACT, date_value null, display_date "Jan 03".
- Vague wording ("a few days later", "the following week") is APPROXIMATE or RELATIVE --
  never EXACT. Put the original phrase in relative_text.
- Relative ordering always matters more than dates. Populate `order` correctly even when
  every date is unknown.
- Include drug starts and stops, dose changes, event onset, key labs, infections,
  rechallenge and recovery.
- `evidence_text` must be verbatim. Do not add events the text does not describe."""


def suggest_timeline(client, doc: CaseDocument) -> list[TimelineEntry]:
    raw = client.complete_json(
        stage="timeline",
        system=TIMELINE_SYSTEM,
        user=f'{_case_header(doc)}\n\nNARRATIVE:\n"""\n{doc.narrative}\n"""\n\nReconstruct the timeline.',
        schema=TIMELINE_SCHEMA,
        schema_name="timeline_events",
        case_id=doc.demo_case_id,
    )

    events: list[TimelineEntry] = []
    for i, row in enumerate(raw.get("events", [])):
        kind = DateKind(row.get("date_kind") or "UNKNOWN")
        date_value = row.get("date_value")
        # A date attached to non-exact timing is an inference; drop it.
        if date_value and kind is not DateKind.EXACT:
            date_value = None
        if kind is DateKind.EXACT and not date_value and not row.get("display_date"):
            kind = DateKind.UNKNOWN

        events.append(
            TimelineEntry(
                id=_uid("evt"),
                label=row.get("label", ""),
                category=row.get("category") or "OTHER",
                order_index=int(row.get("order") or i + 1),
                date_kind=kind,
                date_value=date_value,
                display_date=row.get("display_date"),
                relative_text=row.get("relative_text"),
                actor=row.get("actor"),
                timing_uncertain=kind in (DateKind.APPROXIMATE, DateKind.UNKNOWN),
                ai=_suggestion(doc.narrative, row.get("label"), row.get("evidence_text"), 0.8),
                reviewer_status=ReviewerStatus.AI_SUGGESTED,
                origin=Origin.AI,
            )
        )

    events.sort(key=lambda e: e.order_index)
    for i, event in enumerate(events, start=1):
        event.order_index = i
    return events


# ---------------------------------------------------------------------------
# classify_evidence_relationship() -- the causality dimensions
# ---------------------------------------------------------------------------

DIMENSION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "answer": {"type": "string", "description": "YES, NO, UNKNOWN, or a short phrase."},
                    "rationale": {"type": "string"},
                    "evidence_text": {"type": ["string", "null"]},
                    "confidence": {"type": "number"},
                },
            },
        }
    },
}

DIMENSION_SYSTEM = """You answer structured causality-investigation questions about a case, so a
pharmacovigilance reviewer can confirm or correct each one.

Rules:
- Answer UNKNOWN whenever the narrative does not state the information. UNKNOWN is a
  correct and valuable answer here.
- Absence of evidence is not evidence of absence. If a rechallenge or a placebo was never
  performed, that is UNKNOWN / NOT PERFORMED -- never a negative finding.
- Every non-UNKNOWN answer needs a verbatim quote from the narrative.
- Your quote must support the SPECIFIC question. For "did the event improve after
  stopping", quote the improvement, not the stopping."""


def suggest_dimensions(client, doc: CaseDocument) -> list[DimensionQuestion]:
    prompts: list[str] = []
    for dimension, questions in DIMENSION_QUESTIONS.items():
        prompts.append(f"\n[{dimension.value}]")
        prompts.extend(f"  {key}: {text}" for key, text in questions)

    raw = client.complete_json(
        stage="dimensions",
        system=DIMENSION_SYSTEM,
        user=(
            f'{_case_header(doc)}\n\nNARRATIVE:\n"""\n{doc.narrative}\n"""\n\n'
            f"Answer each question, using its key:{''.join(prompts)}"
        ),
        schema=DIMENSION_SCHEMA,
        schema_name="causality_dimensions",
        case_id=doc.demo_case_id,
    )
    by_key = {r.get("key"): r for r in raw.get("answers", [])}

    out: list[DimensionQuestion] = []
    for dimension, questions in DIMENSION_QUESTIONS.items():
        for key, text in questions:
            row = by_key.get(key, {})
            out.append(
                DimensionQuestion(
                    id=f"dim-{key}",
                    dimension=dimension,
                    key=key,
                    question=text,
                    ai=_suggestion(
                        doc.narrative,
                        row.get("answer", "UNKNOWN"),
                        row.get("evidence_text"),
                        row.get("confidence", 0.0),
                        row.get("rationale", ""),
                    ),
                    reviewer_status=ReviewerStatus.AI_SUGGESTED,
                    origin=Origin.AI,
                )
            )
    return out


# ---------------------------------------------------------------------------
# suggest_alternative_causes()
# ---------------------------------------------------------------------------

_EVIDENCE_ARRAY = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "statement": {"type": "string"},
            "evidence_text": {"type": ["string", "null"]},
        },
    },
}

HYPOTHESES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "hypotheses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": [
                            "SUSPECT_DRUG", "CONCOMITANT_DRUG", "INFECTION", "UNDERLYING_DISEASE",
                            "ALCOHOL", "PROCEDURE", "DISEASE_PROGRESSION", "INTERACTION", "OTHER",
                        ],
                    },
                    "is_suspected_drug": {"type": "boolean"},
                    "assessment": {
                        "type": "string",
                        "enum": [level.value for level in AssessmentLevel],
                    },
                    "rationale": {"type": "string"},
                    "supporting": _EVIDENCE_ARRAY,
                    "contradicting": _EVIDENCE_ARRAY,
                    "unknown": _EVIDENCE_ARRAY,
                },
            },
        }
    },
}

HYPOTHESES_SYSTEM = """You enumerate competing explanations for an adverse event so a reviewer can
weigh them against each other.

Always include the suspected drug, plus every alternative the narrative supports:
concomitant medications, recently stopped medications, infection, underlying disease,
disease progression, alcohol or supplements, a procedure, or an unrelated condition.

Sort each hypothesis's evidence into three buckets:
- supporting: facts making this cause more likely
- contradicting: facts arguing against it (e.g. the drug continued while the patient recovered)
- unknown: decisive information the narrative does not provide

Rules:
- NEVER output a numeric probability or percentage. Use only the allowed qualitative levels.
- Do not let the suspected drug win by default. Apply identical scrutiny to every candidate.
- Supporting and contradicting points need a verbatim quote. Unknown points describe what
  is absent, so their evidence_text is null.
- Your assessment is a SUGGESTION for a human to overrule. Say "Insufficient evidence"
  whenever that is the honest answer."""


def suggest_hypotheses(client, doc: CaseDocument) -> list[Hypothesis]:
    raw = client.complete_json(
        stage="hypotheses",
        system=HYPOTHESES_SYSTEM,
        user=(
            f'{_case_header(doc)}\n\nNARRATIVE:\n"""\n{doc.narrative}\n"""\n\n'
            "Enumerate every plausible competing explanation."
        ),
        schema=HYPOTHESES_SCHEMA,
        schema_name="competing_hypotheses",
        case_id=doc.demo_case_id,
    )

    out: list[Hypothesis] = []
    for row in raw.get("hypotheses", []):
        hid = _uid("hyp")
        evidence: list[HypothesisEvidence] = []
        for bucket, valence in (
            ("supporting", EvidenceValence.SUPPORTING),
            ("contradicting", EvidenceValence.CONTRADICTING),
            ("unknown", EvidenceValence.UNKNOWN),
        ):
            for item in row.get(bucket, []) or []:
                evidence.append(
                    HypothesisEvidence(
                        id=_uid("hev"),
                        valence=valence,
                        statement=item.get("statement", ""),
                        ai=_suggestion(doc.narrative, item.get("statement"), item.get("evidence_text"), 0.75),
                        reviewer_status=ReviewerStatus.AI_SUGGESTED,
                        origin=Origin.AI,
                    )
                )

        level = row.get("assessment") or AssessmentLevel.INSUFFICIENT.value
        try:
            ai_assessment = AssessmentLevel(level)
        except ValueError:
            ai_assessment = AssessmentLevel.INSUFFICIENT

        out.append(
            Hypothesis(
                id=hid,
                label=row.get("label", ""),
                kind=row.get("kind") or "OTHER",
                is_suspected_drug=bool(row.get("is_suspected_drug")),
                ai_assessment=ai_assessment,
                ai_rationale=row.get("rationale", ""),
                reviewer_status=ReviewerStatus.AI_SUGGESTED,
                origin=Origin.AI,
                evidence=evidence,
            )
        )
    return out


# ---------------------------------------------------------------------------
# suggest_missing_evidence()  -- new
# ---------------------------------------------------------------------------

MISSING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "The information that is absent."},
                    "why_it_matters": {
                        "type": "string",
                        "description": "How obtaining it would change the assessment.",
                    },
                    "affects": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Which hypotheses or dimensions it would help resolve.",
                    },
                },
            },
        }
    },
}

MISSING_SYSTEM = """You identify information that is ABSENT from an adverse drug event case and
whose absence materially limits the causality assessment.

You are helping a reviewer decide what to go and look for. Be specific and practical.

Rules:
- Only list information that is genuinely missing. Do not list things the case already
  states.
- For each, explain how having it would actually change the assessment -- especially where
  it would discriminate between two competing explanations. Vague wishes are useless.
- Phrase each as a suggestion to investigate, not as a criticism of the report.
- Prioritise: rechallenge status, dechallenge timing, competing-cause workup, baseline
  values before exposure, dose and timing details, and prior exposure history.
- Do not propose anything that would require identifying the patient."""


def suggest_missing_evidence(client, doc: CaseDocument) -> list[MissingEvidenceItem]:
    """Built on reviewer-confirmed evidence, so it reflects the case as the
    human has actually validated it -- not the model's own first pass."""
    digest = confirmed_evidence_digest(doc)
    raw = client.complete_json(
        stage="missing",
        system=MISSING_SYSTEM,
        user=(
            f'{_case_header(doc)}\n\nNARRATIVE:\n"""\n{doc.narrative}\n"""\n\n'
            f"WHAT THE REVIEWER HAS CONFIRMED SO FAR:\n{digest}\n\n"
            "What information is missing that would most reduce uncertainty?"
        ),
        schema=MISSING_SCHEMA,
        schema_name="missing_evidence",
        case_id=doc.demo_case_id,
    )
    return [
        MissingEvidenceItem(
            id=_uid("miss"),
            prompt=row.get("prompt", ""),
            why_it_matters=row.get("why_it_matters", ""),
            affects=[str(a) for a in (row.get("affects") or [])],
            origin=Origin.AI,
        )
        for row in raw.get("items", [])
    ]


# ---------------------------------------------------------------------------
# Naranjo + WHO-UMC suggestions
# ---------------------------------------------------------------------------


def suggest_naranjo(client, doc: CaseDocument) -> dict[int, AiSuggestion]:
    """Ask for per-item answers. Returns suggestions keyed by item number.

    The caller merges these into the existing items without touching any
    reviewer answer, and the total is never computed here.
    """
    items = naranjo_answer_items(
        client,
        narrative=doc.narrative,
        suspected_drug=doc.suspected_drug,
        adverse_event=doc.adverse_event,
        case_id=doc.demo_case_id,
    )
    out: dict[int, AiSuggestion] = {}
    for item in items:
        out[item.number] = AiSuggestion(
            value=item.answer.value,
            rationale=item.rationale,
            evidence_text=item.evidence_text,
            span=item.span,
            confidence=0.0,
            verification=Verdict(item.verdict.value) if item.verdict else None,
        )
    return out


def suggest_who_umc(client, doc: CaseDocument) -> WhoUmcReview:
    result = who_umc_service.assess(
        client,
        narrative=doc.narrative,
        suspected_drug=doc.suspected_drug,
        adverse_event=doc.adverse_event,
        case_id=doc.demo_case_id,
    )
    evidence = [
        HypothesisEvidence(
            id=_uid("wev"),
            valence=EvidenceValence.SUPPORTING,
            statement=item.statement,
            ai=_suggestion(doc.narrative, item.statement, item.evidence_text, 0.7),
            reviewer_status=ReviewerStatus.AI_SUGGESTED,
            origin=Origin.AI,
        )
        for item in result.supporting_evidence
    ]
    return WhoUmcReview(
        ai_classification=result.classification,
        ai_reasoning=result.reasoning,
        ai_major_uncertainty=result.major_uncertainty,
        key_evidence=evidence,
        reviewer_status=ReviewerStatus.AI_SUGGESTED,
    )


# ---------------------------------------------------------------------------
# lookup_known_reaction()  -- retrieval-grounded, for Naranjo item 1
# ---------------------------------------------------------------------------

LABEL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "mentions_event": {
            "type": ["boolean", "null"],
            "description": "true if the label describes this reaction, false if not, null if unclear.",
        },
        "quote": {
            "type": ["string", "null"],
            "description": "Verbatim span copied from the label, or null.",
        },
        "section": {"type": ["string", "null"]},
        "reasoning": {"type": "string"},
    },
}

LABEL_SYSTEM = """You decide whether an approved product label describes a particular adverse
reaction. You are given the label text; use nothing else.

Clinical synonymy counts. "Fulminant hepatic necrosis", "hepatitis", "elevated transaminases"
and "jaundice" all describe liver injury. "Agranulocytosis" does not.

Rules:
- `quote` must be copied character-for-character from the label text supplied. Never
  paraphrase it, never tidy the capitalisation, and never quote anything not in the text.
- Quote the most specific sentence that names the reaction, not the section heading.
- Set mentions_event false only when you have read the label and the reaction is genuinely
  absent. Use null if the label is too vague to tell.
- Do not judge causality for this patient, and do not answer the Naranjo item. You are
  retrieving evidence for a human to weigh."""


def match_label_evidence(client, drug: str, adverse_event: str, text: str) -> dict[str, Any]:
    """Ask whether the retrieved label text describes the event.

    The model sees only the label, so its answer is grounded in retrieved text
    rather than recalled from training. The caller then verifies the quote is
    genuinely present.
    """
    raw = client.complete_json(
        stage="label_match",
        system=LABEL_SYSTEM,
        user=(
            f"Suspected drug: {drug}\nAdverse event to look for: {adverse_event}\n\n"
            f'LABEL TEXT:\n"""\n{text}\n"""\n\n'
            "Does this label describe that reaction?"
        ),
        schema=LABEL_SCHEMA,
        schema_name="label_match",
    )
    return raw


# ---------------------------------------------------------------------------
# draft_reviewer_rationale()  -- new
# ---------------------------------------------------------------------------

RATIONALE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "rationale": {"type": "string", "description": "3-6 sentences of plain clinical prose."}
    },
}

RATIONALE_SYSTEM = """You draft a causality rationale for a pharmacovigilance reviewer to edit and
sign.

You will be shown ONLY evidence the reviewer has already confirmed, plus their own
conclusions. Write from that and nothing else.

Rules:
- Use only the confirmed evidence supplied. Do not reintroduce anything the reviewer
  rejected, and do not add clinical knowledge of your own.
- State the temporal relationship, the dechallenge and rechallenge status, the competing
  explanations considered, and what could not be determined.
- Name the limitations plainly. If rechallenge was not performed or a competing cause was
  never excluded, say so.
- Never claim the assessment establishes causation, and never state a numeric probability.
- Write 3-6 sentences of neutral clinical prose. No headings, no bullet points, no
  hedging filler."""


def draft_rationale(client, doc: CaseDocument, framework_summary: str) -> str:
    digest = confirmed_evidence_digest(doc)
    conclusion = doc.conclusion
    reviewer_bits = []
    if conclusion.final_assessment:
        reviewer_bits.append(f"Reviewer's final assessment: {conclusion.final_assessment}")
    if conclusion.primary_cause_hypothesis_id:
        hypothesis = doc.find_hypothesis(conclusion.primary_cause_hypothesis_id)
        if hypothesis:
            reviewer_bits.append(f"Reviewer's primary suspected cause: {hypothesis.label}")

    raw = client.complete_json(
        stage="rationale",
        system=RATIONALE_SYSTEM,
        user=(
            f"{_case_header(doc)}\n\n"
            f"{chr(10).join(reviewer_bits)}\n\n"
            f"FRAMEWORK RESULTS:\n{framework_summary}\n\n"
            f"REVIEWER-CONFIRMED EVIDENCE:\n{digest}\n\n"
            "Draft the rationale."
        ),
        schema=RATIONALE_SCHEMA,
        schema_name="reviewer_rationale",
        case_id=doc.demo_case_id,
    )
    return raw.get("rationale", "").strip()
