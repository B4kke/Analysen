"""PDF text/table extraction executor (no financial claims).

Runs one admitted lead that carries a ``{"document_id": ...}`` value: the
referenced document must already be attached to the investigation, its raw
bytes are read from the hash-addressed raw store, and the injected
``pdf_extract`` boundary (matching ``extract_pdf_document``) produces page
texts and table counts. The document row is refreshed with the extracted
text and merged parser metadata. No financial claims are created here
(separate AQ-019 mapping owns those).
"""

import inspect
import json
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.config import get_settings
from apps.api.app.domain.models import Lead
from apps.api.app.repositories import claims_evidence
from apps.api.app.repositories import investigations as repository
from apps.api.app.services.pdf_extraction import PdfDependenciesMissing

PdfExtractFn = Any


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


async def execute_pdf_process(
    session: AsyncSession,
    investigation_id: UUID,
    lead_id: UUID,
    lead: Lead,
    pdf_extract: PdfExtractFn,
) -> str:
    """Execute one PDF-process lead; return the terminal status.

    Terminal statuses: COMPLETED or FAILED. Every outcome is audited;
    failures carry a machine-readable blocked_reason. The scope gate
    re-check is done by the caller.
    """
    value = lead.value
    raw_doc_id = value.get("document_id") if isinstance(value, dict) else None
    if not isinstance(raw_doc_id, str):
        return await _fail(session, investigation_id, lead_id, "invalid_pdf_value")
    try:
        document_uuid = UUID(raw_doc_id)
    except (ValueError, AttributeError):
        return await _fail(session, investigation_id, lead_id, "invalid_pdf_value")

    await repository.set_lead_status(session, investigation_id, lead_id, "RUNNING")

    row = (
        await session.execute(
            text(
                "SELECT d.* FROM documents d "
                "JOIN investigation_documents idoc ON idoc.document_id = d.id "
                "WHERE d.id = :did AND idoc.investigation_id = :iid"
            ),
            {"did": document_uuid, "iid": investigation_id},
        )
    ).mappings().one_or_none()
    if row is None:
        return await _fail(session, investigation_id, lead_id, "document_not_found")
    doc = dict(row)

    storage_key = doc.get("raw_storage_key")
    if not isinstance(storage_key, str) or not storage_key:
        return await _fail(session, investigation_id, lead_id, "raw_snapshot_missing")
    try:
        raw_bytes = (Path(get_settings().raw_evidence_dir) / storage_key).read_bytes()
    except OSError:
        return await _fail(session, investigation_id, lead_id, "raw_snapshot_missing")

    try:
        extracted = pdf_extract(raw_bytes)
        if inspect.isawaitable(extracted):
            extracted = await extracted
    except PdfDependenciesMissing:
        return await _fail(session, investigation_id, lead_id, "dependency_unavailable")
    except Exception as exc:
        return await _fail(
            session, investigation_id, lead_id, f"source_error:{type(exc).__name__}"
        )

    pages = getattr(extracted, "pages", None) or []
    texts: list[str] = [(getattr(page, "text", "") or "") for page in pages]
    extracted_text = "\n\n".join(texts)
    total_tables = 0
    for page in pages:
        tables = getattr(page, "tables", None) or []
        try:
            total_tables += len(tables)
        except TypeError:
            continue

    existing_metadata = doc.get("parser_metadata") or {}
    if isinstance(existing_metadata, str):
        try:
            existing_metadata = json.loads(existing_metadata)
        except ValueError:
            existing_metadata = {}
    if not isinstance(existing_metadata, dict):
        existing_metadata = {}
    merged_metadata = {
        **existing_metadata,
        "pdf_pages": len(pages),
        "pdf_tables": total_tables,
    }

    original_url = doc.get("original_url") or ""
    canonical_url = doc.get("canonical_url") or ""
    sha256 = doc.get("sha256")
    if not isinstance(sha256, str) or not sha256:
        return await _fail(session, investigation_id, lead_id, "document_not_found")
    await claims_evidence.upsert_document(
        session,
        source_id=doc.get("source_id"),
        original_url=original_url,
        canonical_url=canonical_url,
        mime_type=doc.get("mime_type") or "application/pdf",
        sha256=sha256,
        raw_storage_key=doc.get("raw_storage_key"),
        extracted_text=extracted_text,
        parser_metadata=merged_metadata,
    )
    # upsert_document preserves a non-empty parser_metadata/extracted_text on
    # conflict, so force the merged PDF fields to land deterministically.
    await session.execute(
        text(
            "UPDATE documents SET extracted_text = :text, "
            "parser_metadata = CAST(:meta AS jsonb) WHERE id = :did"
        ),
        {"text": extracted_text, "meta": json.dumps(merged_metadata), "did": document_uuid},
    )
    await claims_evidence.attach_document(session, investigation_id, document_uuid)
    await repository.set_lead_status(session, investigation_id, lead_id, "COMPLETED")
    await repository.bump_module_coverage(
        session, investigation_id, lead.scope_area, provider="pdf_extract"
    )
    await repository._audit(
        session,
        investigation_id,
        "LEAD_EXECUTED",
        {
            "lead_id": str(lead_id),
            "status": "COMPLETED",
            "provider": "pdf_extract",
            "document_id": raw_doc_id,
        },
    )
    return "COMPLETED"
