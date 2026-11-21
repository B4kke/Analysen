"""Direct web fetch executor (extraction-only, no claims).

Runs one admitted lead that carries a ``{"url": ...}`` value: the URL is
validated syntactically (the injected fetcher owns SSRF/DNS), the fetch is
performed through the injected ``fetch_doc`` boundary, the exact original bytes
are verified against the immutable snapshot, and extracted text is stored separately.
No claims or evidence are created here.
"""

from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.domain.models import Lead, SourceRegistryRecord
from apps.api.app.repositories import claims_evidence
from apps.api.app.repositories import investigations as repository
from apps.api.app.services.raw_store import RawSnapshotUnavailable, load_raw_bytes
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
    if result.error or not 200 <= result.status_code < 300:
        return await _fail(session, investigation_id, lead_id, "source_error:FetchFailed")
    mime = (result.content_type or "").split(";", 1)[0].lower()
    if mime != "application/pdf" and not (result.content or "").strip():
        return await _fail(session, investigation_id, lead_id, "source_error:FetchFailed")
    metadata = result.metadata
    digest = metadata.get("raw_sha256")
    storage_key = metadata.get("raw_storage_key")
    if (
        not result.raw_bytes
        or not isinstance(digest, str)
        or not isinstance(storage_key, str)
        or result.fetched_at is None
        or result.fetched_at.utcoffset() is None
        or result.url != url
        or metadata.get("source_url") != url
        or metadata.get("final_url") != result.final_url
        or metadata.get("fetched_at") != result.fetched_at.isoformat()
    ):
        return await _fail(session, investigation_id, lead_id, "raw_snapshot_invalid")
    try:
        original = load_raw_bytes(storage_key, digest)
    except RawSnapshotUnavailable:
        return await _fail(session, investigation_id, lead_id, "raw_snapshot_invalid")
    if original != result.raw_bytes:
        return await _fail(session, investigation_id, lead_id, "raw_snapshot_invalid")
    if mime == "application/pdf" and not original.startswith(b"%PDF-"):
        return await _fail(session, investigation_id, lead_id, "invalid_pdf_snapshot")
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
        extracted_text=None if mime == "application/pdf" else result.content,
        parser_metadata={
            "fetcher": "direct",
            "final_url": result.final_url,
            "fetch_metadata": metadata,
        },
        fetched_at=result.fetched_at,
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
