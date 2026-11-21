"""Bounded, case/job-correlated worker heartbeat, not a completion signal."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from uuid import UUID

import structlog
from redis.asyncio import Redis

from apps.api.app.core.config import get_settings
from apps.api.app.domain.models import ResearchPassState, ResearchPassStatus

INTERVAL_SECONDS = 10
FRESH_SECONDS = 30
TTL_SECONDS = 120


def heartbeat_key(investigation_id: UUID, job_id: UUID) -> str:
    return f"analysen:research:heartbeat:{investigation_id}:{job_id}"


def _client() -> Redis:
    settings = get_settings()
    return Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=2,
        socket_timeout=2,
    )


def apply_heartbeat(
    state: ResearchPassState,
    value: bytes | str | None,
    *,
    now: datetime,
) -> None:
    """A missing, invalid or old signal is never a terminal state."""
    if state.status != ResearchPassStatus.RUNNING or state.job_id is None:
        return
    state.heartbeat_status = "missing"
    state.heartbeat_at = None
    if value is None:
        return
    try:
        stamp = datetime.fromisoformat(value.decode() if isinstance(value, bytes) else value)
        if stamp.tzinfo is None:
            return
        age = (now - stamp).total_seconds()
        if age < -5:
            return
    except (ValueError, UnicodeError):
        return
    state.heartbeat_at = stamp
    state.heartbeat_status = "fresh" if age <= FRESH_SECONDS else "stale"


async def populate_heartbeat(investigation_id: UUID, state: ResearchPassState) -> None:
    """Enrich only currently running jobs; Redis failure degrades gracefully."""
    if state.status != ResearchPassStatus.RUNNING or state.job_id is None:
        return
    client = _client()
    try:
        value = await asyncio.wait_for(
            client.get(heartbeat_key(investigation_id, state.job_id)), timeout=2
        )
        apply_heartbeat(state, value, now=datetime.now(UTC))
    except Exception:
        state.heartbeat_status = "unavailable"
    finally:
        with suppress(Exception):
            await client.aclose()


@asynccontextmanager
async def worker_heartbeat(
    investigation_id: UUID,
    job_id: UUID,
) -> AsyncIterator[None]:
    """Refresh an expiring key while the actual worker event loop is responsive.

    No heartbeat is emitted by the API or queue. On stalled/crashed workers the
    signal ages out. An unavailable Redis heartbeat must not abort research.
    A terminal audit event remains the sole authority for completion.
    """
    key = heartbeat_key(investigation_id, job_id)
    client = _client()

    async def pulse() -> None:
        warned = False
        while True:
            try:
                await asyncio.wait_for(
                    client.set(key, datetime.now(UTC).isoformat(), ex=TTL_SECONDS),
                    timeout=2,
                )
                warned = False
            except Exception as exc:
                if not warned:
                    structlog.get_logger().warning(
                        "research_heartbeat_unavailable", error_type=type(exc).__name__
                    )
                    warned = True
            await asyncio.sleep(INTERVAL_SECONDS)

    task = asyncio.create_task(pulse())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        # Keep the most recent timestamp for a crashed worker until TTL expiry.
        # Terminal jobs never expose heartbeat fields, so there is no need to
        # delete or risk racing another operation.
        with suppress(Exception):
            await client.aclose()
