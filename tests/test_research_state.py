"""Correlation/phase regressions for durable research state (AQ-025)."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from apps.api.app.services.research_state import reduce_research_events

TIME = datetime(2026, 9, 18, tzinfo=UTC)
SUMMARY = {"executed": 1, "blocked": 0, "failed": 0, "stopped_reason": "no_executable_leads"}


def event(index, phase, job_id=None, **payload):
    return {
        "id": index,
        "created_at": TIME + timedelta(seconds=index),
        "event_type": f"RESEARCH_PASS_{phase}",
        "payload": {**({"job_id": str(job_id)} if job_id else {}), **payload},
    }


def test_completed_worker_wins_late_enqueue_and_broker_error():
    job = uuid4()
    state = reduce_research_events(
        [
            event(1, "REQUESTED", job),
            event(2, "STARTED", job),
            event(3, "COMPLETED", job, summary=SUMMARY),
            event(4, "FAILED", job, error_code="enqueue_failed"),
            event(5, "ENQUEUED", job),
        ]
    )
    assert state.status == "COMPLETED"
    assert state.completed_at == TIME + timedelta(seconds=3)
    assert state.error_code is None
    assert state.enqueued_at == TIME + timedelta(seconds=5)
    assert state.summary.executed == 1


def test_new_job_is_selected_even_when_old_job_completes_later():
    old, new = uuid4(), uuid4()
    state = reduce_research_events(
        [
            event(1, "REQUESTED", old),
            event(2, "REQUESTED", new),
            event(3, "ENQUEUED", new),
            event(4, "COMPLETED", old, summary=SUMMARY),
        ]
    )
    assert state.status == "ENQUEUED"
    assert state.job_id == new
    assert state.summary is None
    assert state.completed_at is None


@pytest.mark.parametrize("job_id", [None, "old-uncorrelated-id"])
def test_legacy_completed_pass_remains_completed(job_id):
    state = reduce_research_events([event(1, "COMPLETED", job_id, summary=SUMMARY)])
    assert state.status == "COMPLETED"
    assert state.legacy_activity
    assert state.job_id is None
    assert state.summary.executed == 1


def test_failed_pass_uses_selected_terminal_time_and_code():
    job = uuid4()
    state = reduce_research_events(
        [
            event(1, "REQUESTED", job),
            event(2, "STARTED", job),
            event(3, "FAILED", job, error_code="research_pass_failed"),
        ]
    )
    assert state.status == "FAILED"
    assert state.completed_at == TIME + timedelta(seconds=3)
    assert state.error_code == "research_pass_failed"
    assert state.summary is None


def test_activity_and_no_activity_have_distinct_states():
    assert reduce_research_events([]).status == "NOT_STARTED"
    assert reduce_research_events([], has_activity=True).status == "ACTIVITY_RECORDED"


def test_invalid_summary_is_not_used_as_a_claim_of_work():
    state = reduce_research_events([event(1, "COMPLETED", uuid4(), summary={"executed": -1})])
    assert state.status == "COMPLETED"
    assert state.summary is None
