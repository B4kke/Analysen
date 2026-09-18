"""Claims and Evidence repository (AQ-020).

Persists claims, evidence, documents, sources and entity resolution data.
"""

import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.domain.models import (
    DocumentRecord,
    SourceRegistryRecord,
)


async def _upsert_source(
    session: AsyncSession,
    source: SourceRegistryRecord,
) -> None:
    await session.execute(
        text("""
            INSERT INTO sources (id, name, evidence_tier, access_class,
                                 base_url, license, metadata)
            VALUES (:id, :name, :evidence_tier, :access_class,
                    :base_url, :license, CAST(:metadata AS jsonb))
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                evidence_tier = EXCLUDED.evidence_tier,
                access_class = EXCLUDED.access_class,
                base_url = EXCLUDED.base_url,
                license = EXCLUDED.license,
                metadata = EXCLUDED.metadata
        """),
        {
            "id": source.id,
            "name": source.name,
            "evidence_tier": source.evidence_tier,
            "access_class": source.access_class,
            "base_url": source.base_url,
            "license": source.license,
            "metadata": json.dumps(source.metadata),
        },
    )


async def _upsert_document(
    session: AsyncSession,
    document: DocumentRecord,
) -> UUID:
    """Insert or update a document by SHA-256 (content-addressed)."""
    row = await session.execute(
        text("""
            INSERT INTO documents (
                source_id, original_url, canonical_url, mime_type,
                sha256, raw_storage_key, extracted_text, parser_metadata
            ) VALUES (
                :source_id, :original_url, :canonical_url, :mime_type,
                :sha256, :raw_storage_key, :extracted_text,
                CAST(:parser_metadata AS jsonb)
            )
            ON CONFLICT (sha256) DO UPDATE SET
                fetched_at = now(),
                original_url = EXCLUDED.original_url,
                canonical_url = EXCLUDED.canonical_url,
                extracted_text = EXCLUDED.extracted_text,
                parser_metadata = EXCLUDED.parser_metadata
            RETURNING id
        """),
        {
            "source_id": document.source_id,
            "original_url": document.original_url,
            "canonical_url": document.canonical_url,
            "mime_type": document.mime_type,
            "sha256": document.sha256,
            "raw_storage_key": document.raw_storage_key,
            "extracted_text": document.extracted_text,
            "parser_metadata": json.dumps(document.parser_metadata),
        },
    )
    return row.scalar_one()


async def _attach_document(
    session: AsyncSession,
    investigation_id: UUID,
    document_id: UUID,
    reason: str = "direct_lookup",
) -> None:
    await session.execute(
        text("""
            INSERT INTO investigation_documents (investigation_id, document_id, reason)
            VALUES (:investigation_id, :document_id, :reason)
            ON CONFLICT (investigation_id, document_id) DO NOTHING
        """),
        {"investigation_id": investigation_id, "document_id": document_id, "reason": reason},
    )


async def _store_evidence(
    session: AsyncSession,
    investigation_id: UUID,
    document_id: UUID,
    locator_type: str,
    locator: dict,
    excerpt: str | None,
    structured_value: dict | None,
) -> UUID:
    """Store an immutable evidence snippet; returns evidence ID."""
    payload = json.dumps(
        {"locator_type": locator_type, "locator": locator, "excerpt": excerpt},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    content_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    # Check if evidence already exists
    existing = await session.execute(
        text("SELECT id FROM evidence WHERE content_hash = :ch"),
        {"ch": content_hash},
    )
    existing_id = existing.scalar_one_or_none()
    if existing_id:
        return existing_id

    # Store new evidence
    row = await session.execute(
        text("""
            INSERT INTO evidence (
                document_id, locator_type, locator, excerpt, structured_value, content_hash
            ) VALUES (
                :document_id, :locator_type, CAST(:locator AS jsonb),
                :excerpt, CAST(:structured_value AS jsonb), :content_hash
            )
            ON CONFLICT (content_hash) DO NOTHING
            RETURNING id
        """),
        {
            "document_id": document_id,
            "locator_type": locator_type,
            "locator": json.dumps(locator),
            "excerpt": excerpt,
            "structured_value": json.dumps(structured_value) if structured_value else None,
            "content_hash": content_hash,
        },
    )
    result = row.scalar_one_or_none()
    if result is None:
        # Another transaction inserted it concurrently
        row = await session.execute(
            text("SELECT id FROM evidence WHERE content_hash = :ch"),
            {"ch": content_hash},
        )
        return row.scalar_one()
    return result


async def _upsert_claim(
    session: AsyncSession,
    investigation_id: UUID,
    subject_entity_id: UUID | None,
    predicate: str,
    value: Any,
    status: str,
    evidence_ids: list[UUID],
) -> UUID:
    """Insert or update a claim."""
    row = await session.execute(
        text("""
            INSERT INTO claims (
                investigation_id, subject_entity_id, predicate, value, status
            ) VALUES (:iid, :seid, :predicate, CAST(:value AS jsonb), :status)
            ON CONFLICT (investigation_id, predicate, value) DO UPDATE SET
                status = EXCLUDED.status,
                subject_entity_id = COALESCE(
                    claims.subject_entity_id, EXCLUDED.subject_entity_id
                ),
                verified_at = CASE
                    WHEN EXCLUDED.status IN ('VERIFIED', 'PARTIALLY_SUPPORTED', 'CONTRADICTED')
                    THEN now() ELSE claims.verified_at END
            RETURNING id
        """),
        {
            "iid": investigation_id,
            "seid": subject_entity_id,
            "predicate": predicate,
            "value": json.dumps(value, default=str),
            "status": status,
        },
    )
    claim_id = row.scalar_one()

    # Link evidence
    for ev_id in evidence_ids:
        await session.execute(
            text("""
                INSERT INTO claim_evidence (claim_id, evidence_id)
                VALUES (:cid, :eid)
                ON CONFLICT (claim_id, evidence_id) DO NOTHING
            """),
            {"cid": claim_id, "eid": ev_id},
        )

    return claim_id


async def get_claim(
    session: AsyncSession,
    claim_id: UUID,
) -> dict[str, Any] | None:
    row = await session.execute(
        text("SELECT * FROM claims WHERE id = :cid"),
        {"cid": claim_id},
    )
    mapping = row.mappings().one_or_none()
    return dict(mapping) if mapping else None


async def list_claims_for_investigation(
    session: AsyncSession,
    investigation_id: UUID,
) -> list[dict]:
    rows = await session.execute(
        text("""
            SELECT c.*, array_agg(e.content_hash) as evidence_hashes
            FROM claims c
            LEFT JOIN claim_evidence ce ON ce.claim_id = c.id
            LEFT JOIN evidence e ON e.id = ce.evidence_id
            WHERE c.investigation_id = :iid
            GROUP BY c.id
            ORDER BY c.created_at
        """),
        {"iid": investigation_id},
    )
    return [dict(row) for row in rows.mappings().all()]


async def upsert_entity(
    session: AsyncSession,
    entity_id: UUID | None,
    schema: str,
    canonical_name: str | None,
    attributes: dict[str, Any],
    resolution_state: str,
) -> UUID:
    if entity_id:
        await session.execute(
            text("""
                UPDATE entities SET schema = :schema, canonical_name = :cn,
                    attributes = CAST(:attrs AS jsonb), resolution_state = :rs
                WHERE id = :eid
            """),
            {
                "eid": entity_id,
                "schema": schema,
                "cn": canonical_name,
                "attrs": json.dumps(attributes),
                "rs": resolution_state,
            },
        )
        return entity_id

    row = await session.execute(
        text("""
            INSERT INTO entities (schema, canonical_name, attributes, resolution_state)
            VALUES (:schema, :cn, CAST(:attrs AS jsonb), :rs)
            RETURNING id
        """),
        {
            "schema": schema,
            "cn": canonical_name,
            "attrs": json.dumps(attributes),
            "rs": resolution_state,
        },
    )
    return row.scalar_one()


async def add_entity_alias(
    session: AsyncSession,
    entity_id: UUID,
    alias: str,
    source_id: str | None = None,
    confidence: float = 1.0,
) -> None:
    await session.execute(
        text("""
            INSERT INTO entity_aliases (entity_id, alias, source_id, confidence)
            VALUES (:eid, :alias, :source_id, :confidence)
            ON CONFLICT (entity_id, alias) DO UPDATE SET
                confidence = EXCLUDED.confidence
        """),
        {"eid": entity_id, "alias": alias, "source_id": source_id, "confidence": confidence},
    )


async def add_entity_relation(
    session: AsyncSession,
    source_id: UUID,
    target_id: UUID,
    relation_type: str,
    confidence: float,
    evidence_ids: list[UUID],
    valid_from: str | None = None,
    valid_to: str | None = None,
) -> UUID:
    row = await session.execute(
        text("""
            INSERT INTO entity_relations (
                source_entity_id, target_entity_id, relation_type,
                confidence, evidence_ids, valid_from, valid_to
            ) VALUES (:sid, :tid, :rt, :conf, :eids, :vf, :vt)
            ON CONFLICT (source_entity_id, target_entity_id, relation_type) DO UPDATE SET
                confidence = EXCLUDED.confidence,
                evidence_ids = EXCLUDED.evidence_ids
            RETURNING id
        """),
        {
            "sid": source_id,
            "tid": target_id,
            "rt": relation_type,
            "conf": confidence,
            "eids": evidence_ids,
            "vf": valid_from,
            "vt": valid_to,
        },
    )
    return row.scalar_one()


async def upsert_source(
    session: AsyncSession,
    source: Any,
) -> None:
    await _upsert_source(session, source)


async def upsert_document(
    session: AsyncSession,
    doc: Any,
) -> UUID:
    return await _upsert_document(session, doc)


async def link_document_to_investigation(
    session: AsyncSession,
    investigation_id: UUID,
    document_id: UUID,
    reason: str = "direct_lookup",
) -> None:
    await _attach_document(session, investigation_id, document_id, reason)


async def store_evidence(
    session: AsyncSession,
    investigation_id: UUID,
    document_id: UUID,
    locator_type: str,
    locator: dict,
    excerpt: str | None,
    structured_value: dict | None,
) -> UUID:
    return await _store_evidence(
        session, investigation_id, document_id, locator_type, locator, excerpt, structured_value
    )


async def upsert_claim(
    session: AsyncSession,
    investigation_id: UUID,
    subject_entity_id: UUID | None,
    predicate: str,
    value: Any,
    status: str,
    evidence_ids: list[UUID],
) -> UUID:
    return await _upsert_claim(
        session,
        investigation_id,
        subject_entity_id,
        predicate,
        value,
        status,
        evidence_ids,
    )


async def get_claims_for_investigation(
    session: AsyncSession,
    investigation_id: UUID,
) -> list[dict]:
    return await list_claims_for_investigation(session, investigation_id)