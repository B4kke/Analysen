"""SearXNG discovery executor: admitted lead -> search_queries row, discovery-only.

Discovery result snippets are never persisted as evidence; they only locate
sources for later fetching through the document-fetch path. Status, audit and
coverage conventions mirror lead_executor: every outcome is terminal
(COMPLETED/FAILED), failures carry a machine-readable blocked_reason, and
every outcome is audited with a LEAD_EXECUTED event. The scope-gate re-check
is the caller's responsibility; the lead arriving here is admitted + PENDING.
No model calls.
"""

import hashlib
from collections.abc import Awaitable, Callable
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.domain.models import Lead
from apps.api.app.domain.scope import QueryClass
from apps.api.app.repositories import investigations as repository
from apps.api.app.sources.base import DiscoveryResult

SearchFn = Callable[[str], Awaitable[list[DiscoveryResult]]]

PROVIDER = "searxng"
DEFAULT_QUERY_CLASS = QueryClass.DISCOVERY_BROAD


async def execute_searxng_discovery(
    session: AsyncSession,
    investigation_id: UUID,
    lead_id: UUID,
    lead: Lead,
    search: SearchFn,
) -> str:
    """Execute one admitted PENDING SearXNG discovery lead; return terminal status.

    Terminal statuses: COMPLETED, FAILED (bad discovery value, unknown
    query class, or source error). The query string is hashed (sha256 hex of
    the exact string) and recorded in search_queries with full provenance
    metadata; the insert is idempotent on (investigation_id, provider,
    query_hash).
    """
    raw_value = lead.value if isinstance(lead.value, dict) else None
    query = raw_value.get("query") if raw_value is not None else None
    if not isinstance(query, str) or len(query.strip()) < 3:
        return await _fail(session, investigation_id, lead_id, "invalid_discovery_value")

    raw_class = raw_value.get("query_class") if raw_value is not None else None
    if raw_class is None:
        query_class = DEFAULT_QUERY_CLASS
    else:
        try:
            query_class = QueryClass(raw_class)
        except ValueError:
            return await _fail(session, investigation_id, lead_id, "invalid_query_class")

    await repository.set_lead_status(session, investigation_id, lead_id, "RUNNING")
    try:
        results = await search(query)
    except Exception as exc:
        return await _fail(session, investigation_id, lead_id, f"source_error:{type(exc).__name__}")

    query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()
    await session.execute(
        text("""
            INSERT INTO search_queries (
                investigation_id, provider, query, query_hash,
                originating_lead_id, scope_area, query_class,
                information_need, reason
            ) VALUES (
                :investigation_id, :provider, :query, :query_hash,
                :originating_lead_id, :scope_area, :query_class,
                :information_need, :reason
            )
            ON CONFLICT (investigation_id, provider, query_hash) DO NOTHING
        """),
        {
            "investigation_id": investigation_id,
            "provider": PROVIDER,
            "query": query,
            "query_hash": query_hash,
            "originating_lead_id": lead_id,
            "scope_area": lead.scope_area.value,
            "query_class": query_class.value,
            "information_need": lead.information_need,
            "reason": lead.reason,
        },
    )
    await repository.set_lead_status(session, investigation_id, lead_id, "COMPLETED")
    await repository.bump_module_coverage(
        session, investigation_id, lead.scope_area, provider=PROVIDER
    )
    await repository._audit(
        session,
        investigation_id,
        "LEAD_EXECUTED",
        {
            "lead_id": str(lead_id),
            "status": "COMPLETED",
            "provider": PROVIDER,
            "query": query,
            "result_count": len(results),
        },
    )
    return "COMPLETED"


async def _fail(session: AsyncSession, investigation_id: UUID, lead_id: UUID, reason: str) -> str:
    await repository.set_lead_status(session, investigation_id, lead_id, "FAILED", reason)
    await repository._audit(
        session,
        investigation_id,
        "LEAD_EXECUTED",
        {"lead_id": str(lead_id), "status": "FAILED", "reason": reason},
    )
    return "FAILED"
