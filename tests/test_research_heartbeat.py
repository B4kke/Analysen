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



@pytest.mark.asyncio
async def test_worker_publishes_scoped_expiring_signal(monkeypatch):
    import asyncio
    import os

    from redis.asyncio import Redis

    from apps.api.app.services import research_heartbeat

    url = os.environ.get("TEST_REDIS_URL")
    if not url:
        pytest.skip("TEST_REDIS_URL is required")
    monkeypatch.setattr(
        research_heartbeat, "_client", lambda: Redis.from_url(url, socket_timeout=2)
    )
    monkeypatch.setattr(research_heartbeat, "INTERVAL_SECONDS", 0.02)
    case, job = uuid4(), uuid4()
    key = heartbeat_key(case, job)
    observer = Redis.from_url(url, socket_timeout=2)
    try:
        async with research_heartbeat.worker_heartbeat(case, job):
            async with asyncio.timeout(3):
                while not await observer.get(key):
                    await asyncio.sleep(0.02)
            assert 0 < await observer.ttl(key) <= research_heartbeat.TTL_SECONDS
            state = ResearchPassState(status=ResearchPassStatus.RUNNING, job_id=job)
            await research_heartbeat.populate_heartbeat(case, state)
            assert state.heartbeat_status == "fresh"
            other = ResearchPassState(status=ResearchPassStatus.RUNNING, job_id=uuid4())
            await research_heartbeat.populate_heartbeat(case, other)
            assert other.heartbeat_status == "missing"
        last = await observer.get(key)
        await asyncio.sleep(0.08)
        assert await observer.get(key) == last
    finally:
        await observer.delete(key)
        await observer.aclose()
