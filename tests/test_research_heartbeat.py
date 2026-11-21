from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from apps.api.app.domain.models import ResearchPassState, ResearchPassStatus
from apps.api.app.services.research_heartbeat import (
    apply_heartbeat,
    heartbeat_key,
)

NOW = datetime(2026, 11, 21, tzinfo=UTC)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (NOW.isoformat().encode(), "fresh"),
        ((NOW - timedelta(seconds=31)).isoformat(), "stale"),
        (None, "missing"),
        ("invalid", "missing"),
        ("2026-11-21T00:00:00", "missing"),
        ((NOW + timedelta(seconds=60)).isoformat(), "missing"),
    ],
)
def test_heartbeat_does_not_decide_job_completion(value, expected):
    state = ResearchPassState(status=ResearchPassStatus.RUNNING, job_id=uuid4())
    apply_heartbeat(state, value, now=NOW)
    assert state.heartbeat_status == expected
    assert state.status == ResearchPassStatus.RUNNING


def test_terminal_state_ignores_late_heartbeat():
    state = ResearchPassState(status=ResearchPassStatus.COMPLETED, job_id=uuid4())
    apply_heartbeat(state, NOW.isoformat(), now=NOW)
    assert state.heartbeat_at is None
    assert state.heartbeat_status == "not_applicable"


def test_distinct_case_and_job_keys():
    case, job = uuid4(), uuid4()
    assert heartbeat_key(case, job) != heartbeat_key(case, uuid4())
    assert heartbeat_key(case, job) != heartbeat_key(uuid4(), job)


@pytest.mark.asyncio
async def test_redis_failure_does_not_hide_investigation(monkeypatch):
    from apps.api.app.services import research_heartbeat

    class BrokenClient:
        async def get(self, _key):
            raise OSError("unavailable")

        async def aclose(self):
            pass

    monkeypatch.setattr(research_heartbeat, "_client", BrokenClient)
    state = ResearchPassState(status=ResearchPassStatus.RUNNING, job_id=uuid4())
    await research_heartbeat.populate_heartbeat(uuid4(), state)
    assert state.heartbeat_status == "unavailable"
    assert state.status == ResearchPassStatus.RUNNING
