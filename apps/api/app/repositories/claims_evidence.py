"""Claims and Evidence repository (AQ-020, reconciled with baseline in 0004).

Persists sources, documents, evidence, claims, entities, aliases and
relationships against the canonical shapes that 0001_baseline plus the
0004_claims_reconcile migration guarantee:

- evidence.content_hash is the content-addressed dedup key,
- claims.fingerprint (investigation + predicate + canonical value) is the
  idempotency key,
- claim_evidence uses the baseline `relation` column
  (supports/contradicts/context),
- entity_aliases keeps the baseline shape plus a confidence column,
- relationships is the canonical relation table.
"""

import hashlib
import json
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.domain.models import ClaimStatus, SourceRegistryRecord
from apps.api.app.services.entity_resolution import normalize_name


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def evidence_content_hash(
    document_id: UUID, locator_type: str, locator: dict, excerpt: str | None
) -> str:
    """Content-addressed digest; identical formula is the dedup contract.

    document_id is part of the hash so identical excerpts in different
    documents do not alias to the first document's evidence row.
    """
    return hashlib.sha256(
        _canonical_json(
            {
                "document_id": str(document_id),
                "locator_type": locator_type,
                "locator": locator,
                "excerpt": excerpt,
            }
        ).encode()
    ).hexdigest()


def claim_fingerprint(investigation_id: UUID, predicate: str, value: Any) -> str:
    """Idempotency key: same investigation + predicate + value, same claim."""
    return hashlib.sha256(
        f"{investigation_id}:{predicate}:{_canonical_json(value)}".encode()
    ).hexdigest()


def _role_to_relation(role: str) -> str:
    mapping = {"SUPPORTS": "supports", "CONTRADICTS": "contradicts", "PARTIAL": "context"}
    try:
        return mapping[role]
    except KeyError as exc:
        raise ValueError(f"unknown claim evidence role: {role}") from exc


async def upsert_source(session: AsyncSession, source: SourceRegistryRecord) -> None:
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


async def upsert_document(
    session: AsyncSession,
    *,
    source_id: str | None,
    original_url: str,
    canonical_url: str,
    mime_type: str,
    sha256: str,
    raw_storage_key: str | None,
    extracted_text: str | None,
    parser_metadata: dict,
    fetched_at: datetime | None = None,
) -> UUID:
    """Insert or refresh a document by SHA-256 (content-addressed)."""
    row = (
        await session.execute(
            text("""
                INSERT INTO documents (
                    source_id, original_url, canonical_url, mime_type,
                    sha256, raw_storage_key, extracted_text, parser_metadata, fetched_at
                ) VALUES (
                    :source_id, :original_url, :canonical_url, :mime_type,
                    :sha256, :raw_storage_key, :extracted_text,
                    CAST(:parser_metadata AS jsonb), COALESCE(:fetched_at, now())
                )
                ON CONFLICT (sha256) DO UPDATE SET
                    source_id = COALESCE(documents.source_id, EXCLUDED.source_id),
                    original_url = COALESCE(documents.original_url, EXCLUDED.original_url),
                    canonical_url = COALESCE(documents.canonical_url, EXCLUDED.canonical_url),
                    mime_type = COALESCE(documents.mime_type, EXCLUDED.mime_type),
                    extracted_text = COALESCE(documents.extracted_text, EXCLUDED.extracted_text),
                    parser_metadata = CASE
                        WHEN documents.parser_metadata = '{}'::jsonb
                        THEN EXCLUDED.parser_metadata
                        ELSE documents.parser_metadata
                    END,
                    raw_storage_key = COALESCE(
                        documents.raw_storage_key, EXCLUDED.raw_storage_key
                    )
                RETURNING id
            """),
            {
                "source_id": source_id,
                "original_url": original_url,
                "canonical_url": canonical_url,
                "mime_type": mime_type,
                "sha256": sha256,
                "raw_storage_key": raw_storage_key,
                "extracted_text": extracted_text,
                "parser_metadata": json.dumps(parser_metadata),
                "fetched_at": fetched_at,
            },
        )
    ).mappings().one()
    return row["id"]


async def attach_document(
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


async def store_evidence(
    session: AsyncSession,
    document_id: UUID,
    locator_type: str,
    locator: dict,
    excerpt: str | None,
    structured_value: dict | None,
) -> UUID:
    """Store an immutable evidence snippet; idempotent on content hash."""
    content_hash = evidence_content_hash(document_id, locator_type, locator, excerpt)
    row = (
        await session.execute(
            text("""
                INSERT INTO evidence (
                    document_id, locator_type, locator, excerpt,
                    structured_value, content_hash
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
    ).mappings().one_or_none()
    if row is not None:
        return row["id"]
    existing = (
        await session.execute(
            text("SELECT id FROM evidence WHERE content_hash = :ch"),
            {"ch": content_hash},
        )
    ).mappings().one()
    return existing["id"]


async def upsert_claim(
    session: AsyncSession,
    investigation_id: UUID,
    subject_entity_id: UUID | None,
    predicate: str,
    value: Any,
    status: str,
    evidence_ids: list[UUID],
    evidence_role: str = "SUPPORTS",
) -> UUID:
    """Insert or refresh a claim by fingerprint; link evidence."""
    try:
        canonical_status = ClaimStatus(status).value
    except ValueError as exc:
        raise ValueError(f"unsupported claim status: {status}") from exc
    if canonical_status in {
        ClaimStatus.SUPPORTED.value,
        ClaimStatus.PARTIALLY_SUPPORTED.value,
        ClaimStatus.CONTRADICTED.value,
    } and not evidence_ids:
        raise ValueError(
            f"{canonical_status} claims require at least one evidence link"
        )
    relation = _role_to_relation(evidence_role)
    if canonical_status == ClaimStatus.SUPPORTED.value and relation != "supports":
        raise ValueError("SUPPORTED claims require SUPPORTS evidence")
    if canonical_status == ClaimStatus.PARTIALLY_SUPPORTED.value and relation != "supports":
        raise ValueError("PARTIALLY_SUPPORTED claims require SUPPORTS evidence")
    if canonical_status == ClaimStatus.CONTRADICTED.value and relation != "contradicts":
        raise ValueError("CONTRADICTED claims require CONTRADICTS evidence")
    for evidence_id in set(evidence_ids):
        evidence = await session.execute(
            text("""
                SELECT 1
                FROM evidence e
                JOIN investigation_documents d ON d.document_id = e.document_id
                WHERE e.id = :eid AND d.investigation_id = :iid
                LIMIT 1
            """),
            {"eid": evidence_id, "iid": investigation_id},
        )
        if evidence.scalar_one_or_none() is None:
            raise ValueError(
                "evidence must exist and be attached to the investigation"
            )
    fingerprint = claim_fingerprint(investigation_id, predicate, value)
    row = (
        await session.execute(
            text("""
                INSERT INTO claims (
                    investigation_id, subject_entity_id, predicate, value,
                    status, fingerprint, verified_at
                ) VALUES (
                    :iid, :seid, :predicate, CAST(:value AS jsonb),
                    :status, :fingerprint,
                    CASE WHEN :status IN (
                        'SUPPORTED', 'PARTIALLY_SUPPORTED', 'CONTRADICTED'
                    ) THEN now() ELSE NULL END
                )
                ON CONFLICT (investigation_id, fingerprint) DO UPDATE SET
                    status = EXCLUDED.status,
                    subject_entity_id = COALESCE(
                        claims.subject_entity_id, EXCLUDED.subject_entity_id
                    ),
                    value = EXCLUDED.value,
                    verified_at = CASE
                        WHEN EXCLUDED.status IN (
                            'SUPPORTED', 'PARTIALLY_SUPPORTED', 'CONTRADICTED'
                        ) THEN now()
                        ELSE NULL
                    END
                RETURNING id
            """),
            {
                "iid": investigation_id,
                "seid": subject_entity_id,
                "predicate": predicate,
                "value": _canonical_json(value),
                "status": canonical_status,
                "fingerprint": fingerprint,
            },
        )
    ).mappings().one()
    claim_id = row["id"]
    for evidence_id in evidence_ids:
        await session.execute(
            text("""
                INSERT INTO claim_evidence (claim_id, evidence_id, relation)
                VALUES (:cid, :eid, :relation)
                ON CONFLICT DO NOTHING
            """),
            {"cid": claim_id, "eid": evidence_id, "relation": relation},
        )
    return claim_id


async def get_claim(session: AsyncSession, claim_id: UUID) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text("SELECT * FROM claims WHERE id = :cid"),
            {"cid": claim_id},
        )
    ).mappings().one_or_none()
    return dict(row) if row else None


async def list_claims_for_investigation(
    session: AsyncSession, investigation_id: UUID
) -> list[dict]:
    rows = (
        await session.execute(
            text("""
                SELECT c.*,
                    COALESCE(array_agg(DISTINCT e.content_hash)
                        FILTER (WHERE e.id IS NOT NULL), '{}') AS evidence_hashes
                FROM claims c
                LEFT JOIN claim_evidence ce ON ce.claim_id = c.id
                LEFT JOIN evidence e ON e.id = ce.evidence_id
                WHERE c.investigation_id = :iid
                GROUP BY c.id
                ORDER BY c.created_at
            """),
            {"iid": investigation_id},
        )
    ).mappings().all()
    return [dict(row) for row in rows]


async def upsert_entity(
    session: AsyncSession,
    *,
    entity_id: UUID | None,
    schema: str,
    canonical_name: str | None,
    attributes: dict[str, Any],
    resolution_state: str,
) -> UUID:
    """Insert or refresh an entity; always maintains normalized_name."""
    normalized = normalize_name(canonical_name) if canonical_name else None
    if entity_id is not None:
        await session.execute(
            text("""
                UPDATE entities
                SET schema = :schema, canonical_name = :cn,
                    normalized_name = :normalized,
                    attributes = CAST(:attrs AS jsonb),
                    resolution_state = :rs, updated_at = now()
                WHERE id = :eid
            """),
            {
                "eid": entity_id,
                "schema": schema,
                "cn": canonical_name,
                "normalized": normalized,
                "attrs": json.dumps(attributes),
                "rs": resolution_state,
            },
        )
        return entity_id
    row = (
        await session.execute(
            text("""
                INSERT INTO entities (
                    schema, canonical_name, normalized_name, attributes,
                    resolution_state
                ) VALUES (:schema, :cn, :normalized, CAST(:attrs AS jsonb), :rs)
                RETURNING id
            """),
            {
                "schema": schema,
                "cn": canonical_name,
                "normalized": normalized,
                "attrs": json.dumps(attributes),
                "rs": resolution_state,
            },
        )
    ).mappings().one()
    return row["id"]


async def add_entity_alias(
    session: AsyncSession,
    entity_id: UUID,
    alias: str,
    source_id: str | None = None,
    confidence: float = 1.0,
) -> None:
    """Add an alias; existing (entity, normalized alias) rows keep first write."""
    normalized = normalize_name(alias)
    # The baseline schema intentionally permits legacy duplicates. Locking the
    # parent entity makes the check-and-insert atomic without requiring a
    # destructive/downtime-prone deduplication migration.
    await session.execute(
        text("SELECT id FROM entities WHERE id = :eid FOR UPDATE"),
        {"eid": entity_id},
    )
    existing = (
        await session.execute(
            text("""
                SELECT id FROM entity_aliases
                WHERE entity_id = :eid AND normalized_alias = :normalized
                LIMIT 1
            """),
            {"eid": entity_id, "normalized": normalized},
        )
    ).mappings().one_or_none()
    if existing is not None:
        return
    await session.execute(
        text("""
            INSERT INTO entity_aliases (
                entity_id, alias, normalized_alias, source_id, confidence
            ) VALUES (:eid, :alias, :normalized, :source_id, :confidence)
        """),
        {
            "eid": entity_id,
            "alias": alias,
            "normalized": normalized,
            "source_id": source_id,
            "confidence": confidence,
        },
    )


async def add_entity_relation(
    session: AsyncSession,
    source_id: UUID,
    target_id: UUID,
    relation_type: str,
    confidence: float,
    evidence_ids: list[UUID],
    valid_from: date | None = None,
    valid_to: date | None = None,
) -> UUID:
    """Append a relation edge on the canonical relationships table."""
    if not evidence_ids:
        raise ValueError("entity relations require evidence")
    for evidence_id in set(evidence_ids):
        if await session.scalar(
            text("SELECT id FROM evidence WHERE id = :id"), {"id": evidence_id}
        ) is None:
            raise ValueError("entity relation evidence must exist")
    inserted = (
        await session.execute(
            text("""
                INSERT INTO relationships (
                    subject_entity_id, object_entity_id, predicate,
                    confidence, evidence_ids, valid_from, valid_to
                ) VALUES (
                    :sid, :tid, :predicate,
                    :conf, CAST(:eids AS uuid[]), :vf, :vt
                )
                RETURNING id
            """),
            {
                "sid": source_id,
                "tid": target_id,
                "predicate": relation_type,
                "conf": confidence,
                "eids": evidence_ids,
                "vf": valid_from,
                "vt": valid_to,
            },
        )
    ).mappings().one()
    return inserted["id"]
