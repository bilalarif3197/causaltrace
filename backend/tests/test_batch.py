"""Tests for the concurrent first-open analysis.

The parallelism here is easy to get subtly wrong, so these pin the three
properties that matter:

  * stages really do overlap in time (otherwise the feature does nothing);
  * the merged result does not depend on which model call returned first;
  * a stage that reads reviewer-confirmed evidence cannot be batched, because
    it would see an empty case and silently produce a worse answer.
"""

from __future__ import annotations

import threading
import time

import pytest

from schemas.review import ReviewerStatus
from services import store, workspace
from tests.test_api import STAGE_PAYLOADS


class SlowClient:
    """Sleeps per call, so wall-clock time reveals whether stages overlapped."""

    mode = "mock"
    name = "slow-stub"

    def __init__(self, delay: float = 0.25):
        self.delay = delay
        self.lock = threading.Lock()
        self.peak = 0
        self._live = 0

    def complete_json(self, *, stage, system, user, schema, schema_name, case_id=None):
        with self.lock:
            self._live += 1
            self.peak = max(self.peak, self._live)
        try:
            time.sleep(self.delay)
            if stage == "verification":
                ids = [l.split("id: ")[1].strip() for l in user.splitlines() if l.startswith("id: ")]
                return {"verdicts": [{"id": i, "verdict": "SUPPORTED", "reason": "ok"} for i in ids]}
            return STAGE_PAYLOADS.get(stage, {})
        finally:
            with self.lock:
                self._live -= 1


class FlakyClient(SlowClient):
    """Fails one nominated stage, to exercise partial-batch handling."""

    def __init__(self, failing: str):
        super().__init__(delay=0.02)
        self.failing = failing

    def complete_json(self, *, stage, **kw):
        if stage == self.failing:
            raise RuntimeError("provider exploded")
        return super().complete_json(stage=stage, **kw)


def new_case():
    return workspace.create_case(
        narrative=(
            "A 34-year-old woman began TMP-SMX on March 2 for a urinary tract infection. "
            "Five days later she developed fatigue and nausea. On March 16 acute liver "
            "injury was identified with ALT 684 U/L."
        ),
        suspected_drug="TMP-SMX",
        adverse_event="Acute liver injury",
    )


def test_batch_actually_runs_stages_concurrently():
    client = SlowClient(delay=0.3)
    doc = new_case()
    stages = ["timeline", "dimensions", "hypotheses", "naranjo", "who_umc"]

    started = time.perf_counter()
    doc, notes, failed = workspace.run_suggest_batch(client, doc, stages)
    elapsed = time.perf_counter() - started

    assert not failed
    assert len(notes) == len(stages)
    # Sequentially this is 5 x 0.3s = 1.5s. Concurrently it is ~0.3s.
    assert elapsed < 0.9, f"stages did not overlap (took {elapsed:.2f}s)"
    assert client.peak > 1, "no two calls were ever in flight together"


def test_batch_result_is_independent_of_completion_order():
    """Merge order is fixed by the caller, not by whichever call returns first."""
    doc_a = new_case()
    doc_a, _, _ = workspace.run_suggest_batch(
        SlowClient(0.01), doc_a, ["facts", "timeline", "hypotheses"]
    )
    doc_b = new_case()
    doc_b, _, _ = workspace.run_suggest_batch(
        SlowClient(0.01), doc_b, ["facts", "timeline", "hypotheses"]
    )

    assert [f.field for f in doc_a.facts] == [f.field for f in doc_b.facts]
    assert [e.label for e in doc_a.timeline] == [e.label for e in doc_b.timeline]
    assert [h.label for h in doc_a.hypotheses] == [h.label for h in doc_b.hypotheses]


def test_no_stage_is_lost_when_several_write_the_same_document():
    """The bug this endpoint exists to prevent: concurrent whole-document
    saves clobbering each other, so only the last stage survives."""
    doc = new_case()
    doc, _, failed = workspace.run_suggest_batch(SlowClient(0.05), doc, list(workspace.PARALLEL_STAGES))
    assert not failed

    reloaded = store.get_case(doc.id)
    assert reloaded.facts, "facts were lost"
    assert reloaded.timeline, "timeline was lost"
    assert reloaded.dimensions, "dimensions were lost"
    assert reloaded.hypotheses, "hypotheses were lost"
    assert reloaded.who_umc is not None, "who_umc was lost"
    assert any(i.ai_answer for i in reloaded.naranjo), "naranjo was lost"
    assert set(reloaded.stages_run) == set(workspace.PARALLEL_STAGES)


@pytest.mark.parametrize("stage", ["missing", "rationale"])
def test_confirmed_evidence_stages_cannot_be_batched(stage):
    """Batching these would show them a case with nothing confirmed yet."""
    doc = new_case()
    with pytest.raises(workspace.WorkspaceError, match="in parallel"):
        workspace.run_suggest_batch(SlowClient(0.01), doc, ["facts", stage])


def test_unknown_stage_rejected():
    doc = new_case()
    with pytest.raises(workspace.WorkspaceError):
        workspace.run_suggest_batch(SlowClient(0.01), doc, ["facts", "telepathy"])


def test_partial_failure_keeps_the_stages_that_worked():
    doc = new_case()
    doc, notes, failed = workspace.run_suggest_batch(
        FlakyClient("hypotheses"), doc, ["facts", "timeline", "hypotheses"]
    )
    assert "hypotheses" in failed
    assert "provider exploded" in failed["hypotheses"]
    assert doc.facts and doc.timeline, "working stages must still be merged"
    assert doc.hypotheses == []
    # A stage that failed must not be recorded as run, so it can be retried.
    assert "hypotheses" not in doc.stages_run
    assert {"facts", "timeline"} <= set(doc.stages_run)


def test_batch_does_not_clobber_reviewer_decisions():
    doc = new_case()
    doc, _, _ = workspace.run_suggest_batch(SlowClient(0.01), doc, ["facts"])
    target = doc.facts[0].id
    workspace.apply_review(doc, "fact", target, status=ReviewerStatus.MODIFIED, value="mine")

    doc, _, _ = workspace.run_suggest_batch(SlowClient(0.01), store.get_case(doc.id), ["facts"])
    kept = next(f for f in doc.facts if f.id == target)
    assert kept.reviewer_status is ReviewerStatus.MODIFIED
    assert kept.confirmed_value == "mine"


def test_batch_leaves_the_framework_at_zero():
    """Even with every stage run, nothing is confirmed, so nothing scores."""
    doc = new_case()
    doc, _, _ = workspace.run_suggest_batch(SlowClient(0.01), doc, list(workspace.PARALLEL_STAGES))
    framework = workspace.envelope(doc).framework
    assert framework.total_score == 0
    assert framework.unreviewed_count == 10


def test_batch_is_audited_as_one_ai_action():
    doc = new_case()
    doc, _, _ = workspace.run_suggest_batch(SlowClient(0.01), doc, ["facts", "timeline"])
    entries = [e for e in store.get_audit(doc.id) if e.action == "SUGGEST_BATCH"]
    assert len(entries) == 1
    assert entries[0].actor.value == "AI"
    assert set(entries[0].after["stages"]) == {"facts", "timeline"}
