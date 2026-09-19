"""Direct web fetch executor (extraction-only, no claims).

Runs one admitted lead that carries a ``{"url": ...}`` value: the URL is
validated syntactically (the injected fetcher owns SSRF/DNS), the fetch is
performed through the injected ``fetch_doc`` boundary, the exact fetched text
is stored as an immutable raw snapshot, and a ``web_direct`` document is
persisted and attached. No claims or evidence are created here.
"""

from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.domain.models import Lead, SourceRegistryRecord
from apps.api.app.repositories import claims_evidence
from apps.api.app.repositories import investigations as repository
from apps.api.app.services.raw_store import store_raw_snapshot
from apps.api.app.services.url_canonicalization import FetchResult

FetchDoc = Callable[[str], Awaitable[FetchResult]]


async def _fail(
    session: AsyncSession, investigation_id: UUID, lead_id: UUID, reason: str
) -> str:
    await repository.set_lead_status(session, investigation_id, lead_id, "FAILED", reason)
    await repository._audit(
        session,
        investigation_id,
        "LEAD_EXECUTED",
        {"lead_id": str(lead_id), "status": "FAILED", "reason": reason},
    )
    return "FAILED"


async def execute_web_fetch(
    session: AsyncSession,
    investigation_id: UUID,
    lead_id: UUID,
    lead: Lead,
    fetch_doc: FetchDoc,
) -> str:
    """Execute one web-fetch lead; return the terminal status.

    Terminal statuses: COMPLETED or FAILED. Every outcome is audited;
    failures carry a machine-readable blocked_reason. The scope gate
    re-check is done by the caller.
    """
    value = lead.value
    url = value.get("url") if isinstance(value, dict) else None
    if not isinstance(url, str) or not url.strip():
        return await _fail(session, investigation_id, lead_id, "invalid_fetch_url")
    url = url.strip()
    try:
        parts = urlsplit(url)
    except Exception:
        return await _fail(session, investigation_id, lead_id, "invalid_fetch_url")
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return await _fail(session, investigation_id, lead_id, "invalid_fetch_url")

    await repository.set_lead_status(session, investigation_id, lead_id, "RUNNING")
    try:
        result = await fetch_doc(url)
    except Exception as exc:
        return await _fail(
            session, investigation_id, lead_id, f"source_error:{type(exc).__name__}"
        )
    if result.error or not (result.content or "").strip():
        return await _fail(session, investigation_id, lead_id, "source_error:FetchFailed")

    raw_text = result.content
    digest, storage_key = store_raw_snapshot(raw_text)
    source = SourceRegistryRecord(
        id="web_direct",
        name="Direct web fetch",
        evidence_tier=3,
        access_class="PUBLIC_WEB",
        base_url=None,
        license=None,
        metadata={},
    )
    await claims_evidence.upsert_source(session, source)
    document_id = await claims_evidence.upsert_document(
        session,
        source_id="web_direct",
        original_url=url,
        canonical_url=result.final_url,
        mime_type=result.content_type or "text/html",
        sha256=digest,
        raw_storage_key=storage_key,
        extracted_text=None,
        parser_metadata={"fetcher": "direct", "final_url": result.final_url},
    )
    await claims_evidence.attach_document(session, investigation_id, document_id)
    await repository.set_lead_status(session, investigation_id, lead_id, "COMPLETED")
    await repository.bump_module_coverage(
        session, investigation_id, lead.scope_area, provider="web_direct"
    )
    await repository._audit(
        session,
        investigation_id,
        "LEAD_EXECUTED",
        {
            "lead_id": str(lead_id),
            "status": "COMPLETED",
            "provider": "web_direct",
            "url": url,
        },
    )
    return "COMPLETED"
