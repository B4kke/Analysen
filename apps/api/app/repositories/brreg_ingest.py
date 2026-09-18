import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.domain.models import BrregIngestResult, BrregOrganization, ClaimStatus
from apps.api.app.repositories.claims_evidence import (
    claim_fingerprint,
    evidence_content_hash,
    upsert_document,
)
from apps.api.app.services.entity_resolution import normalize_name
from apps.api.app.services.raw_store import store_raw_snapshot
from apps.api.app.sources.base import SourceRecord


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def _ensure_source(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            INSERT INTO sources (id, name, evidence_tier, access_class, base_url, license)
            VALUES (
                'brreg_entities',
                'Brønnøysundregistrene - Enhetsregisteret',
                1,
                'OPEN_NO_KEY',
                'https://data.brreg.no/enhetsregisteret/api',
                'NLOD-2.0'
            )
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                evidence_tier = EXCLUDED.evidence_tier,
                access_class = EXCLUDED.access_class,
                base_url = EXCLUDED.base_url,
                license = EXCLUDED.license
            """
        )
    )


async def _upsert_document(
    session: AsyncSession,
    record: SourceRecord,
) -> UUID:
    payload_json = _canonical_json(record.payload)
    digest = _sha256_text(payload_json)
    # Immutable raw snapshot is written before normalization or any model sees
    # the payload; the digest ties the database row to the stored bytes.
    _, storage_key = store_raw_snapshot(payload_json)
    return await upsert_document(
        session,
        source_id=record.source_id,
        original_url=record.source_url,
        canonical_url=record.source_url,
        mime_type="application/json",
        sha256=digest,
        raw_storage_key=storage_key,
        extracted_text=None,
        parser_metadata={"external_id": record.external_id, "format": "brreg-json"},
    )


async def _attach_document(
    session: AsyncSession,
    investigation_id: UUID,
    document_id: UUID,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO investigation_documents (investigation_id, document_id, reason)
            VALUES (:investigation_id, :document_id, 'direct_registry_lookup')
            ON CONFLICT (investigation_id, document_id) DO NOTHING
            """
        ),
        {"investigation_id": investigation_id, "document_id": document_id},
    )


async def _root_evidence(
    session: AsyncSession,
    document_id: UUID,
    organization: BrregOrganization,
) -> UUID:
    locator = {"pointer": "/"}
    # Canonical content-addressed dedup key (same formula as
    # claims_evidence.store_evidence); NOT NULL since 0004.
    content_hash = evidence_content_hash(document_id, "json_pointer", locator, None)
    row = (
        await session.execute(
            text(
                """
                INSERT INTO evidence (
                    document_id,
                    locator_type,
                    locator,
                    structured_value,
                    content_hash
                )
                VALUES (
                    :document_id,
                    'json_pointer',
                    CAST(:locator AS jsonb),
                    CAST(:structured_value AS jsonb),
                    :content_hash
                )
                ON CONFLICT (content_hash) DO NOTHING
                RETURNING id
                """
            ),
            {
                "document_id": document_id,
                "locator": _canonical_json(locator),
                "structured_value": _canonical_json(
                    organization.model_dump(mode="json", exclude_none=True)
                ),
                "content_hash": content_hash,
            },
        )
    ).mappings().one_or_none()
    if row is not None:
        return row["id"]
    existing = (
        await session.execute(
            text("SELECT id FROM evidence WHERE content_hash = :content_hash"),
            {"content_hash": content_hash},
        )
    ).mappings().one()
    return existing["id"]


async def _upsert_entity(
    session: AsyncSession,
    organization: BrregOrganization,
) -> UUID:
    source_ref = (
        await session.execute(
            text(
                """
                SELECT entity_id
                FROM entity_source_refs
                WHERE source_id = 'brreg_entities' AND external_id = :external_id
                """
            ),
            {"external_id": organization.organization_number},
        )
    ).mappings().one_or_none()

    attributes = organization.model_dump(mode="json", exclude_none=True)
    if source_ref is None:
        entity_row = (
            await session.execute(
                text(
                    """
                    INSERT INTO entities (
                        schema,
                        canonical_name,
                        normalized_name,
                        attributes,
                        resolution_state
                    )
                    VALUES (
                        'Organization',
                        :canonical_name,
                        :normalized_name,
                        CAST(:attributes AS jsonb),
                        'MATCH'
                    )
                    RETURNING id
                    """
                ),
                {
                    "canonical_name": organization.name,
                    "normalized_name": normalize_name(organization.name),
                    "attributes": _canonical_json(attributes),
                },
            )
        ).mappings().one()
        entity_id = entity_row["id"]
        await session.execute(
            text(
                """
                INSERT INTO entity_source_refs (entity_id, source_id, external_id)
                VALUES (:entity_id, 'brreg_entities', :external_id)
                """
            ),
            {"entity_id": entity_id, "external_id": organization.organization_number},
        )
    else:
        entity_id = source_ref["entity_id"]
        await session.execute(
            text(
                """
                UPDATE entities
                SET canonical_name = :canonical_name,
                    normalized_name = :normalized_name,
                    attributes = CAST(:attributes AS jsonb),
                    resolution_state = 'MATCH',
                    updated_at = now()
                WHERE id = :entity_id
                """
            ),
            {
                "entity_id": entity_id,
                "canonical_name": organization.name,
                "normalized_name": normalize_name(organization.name),
                "attributes": _canonical_json(attributes),
            },
        )
    return entity_id


async def _attach_entity(
    session: AsyncSession,
    investigation_id: UUID,
    entity_id: UUID,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO investigation_entities (investigation_id, entity_id, relevance)
            VALUES (:investigation_id, :entity_id, 'direct')
            ON CONFLICT (investigation_id, entity_id) DO UPDATE
            SET relevance = EXCLUDED.relevance
            """
        ),
        {"investigation_id": investigation_id, "entity_id": entity_id},
    )


def _claims_for_organization(organization: BrregOrganization) -> list[tuple[str, Any]]:
    claims: list[tuple[str, Any]] = [
        ("organization_number", organization.organization_number),
        ("legal_name", organization.name),
        ("status_flags", organization.status_flags),
    ]
    optional_values: tuple[tuple[str, Any], ...] = (
        ("organization_form", organization.organization_form_code),
        ("registration_date", organization.registered_at),
        ("foundation_date", organization.foundation_date),
        ("deleted_at", organization.deleted_at),
        ("website", organization.website),
        ("primary_industry_code", organization.primary_industry_code),
    )
    claims.extend((predicate, value) for predicate, value in optional_values if value is not None)
    if organization.historical_names:
        historical_names = [
            item.model_dump(mode="json", exclude_none=True)
            for item in organization.historical_names
        ]
        claims.append(("historical_names", historical_names))
    return claims


async def _upsert_claim(
    session: AsyncSession,
    investigation_id: UUID,
    entity_id: UUID,
    predicate: str,
    value: Any,
    evidence_id: UUID,
) -> UUID:
    json_value = value.isoformat() if hasattr(value, "isoformat") else value
    # Canonical investigation-scoped idempotency key (same formula as
    # claims_evidence.upsert_claim); matches ON CONFLICT (investigation_id, fingerprint).
    fingerprint = claim_fingerprint(investigation_id, predicate, json_value)
    row = (
        await session.execute(
            text(
                """
                INSERT INTO claims (
                    investigation_id,
                    subject_entity_id,
                    predicate,
                    value,
                    status,
                    fingerprint,
                    generated_by,
                    verified_at
                )
                VALUES (
                    :investigation_id,
                    :entity_id,
                    :predicate,
                    CAST(:value AS jsonb),
                    :status,
                    :fingerprint,
                    'source:brreg_entities',
                    CASE WHEN :status IN (
                        'SUPPORTED', 'PARTIALLY_SUPPORTED', 'CONTRADICTED'
                    ) THEN now() ELSE NULL END
                )
                ON CONFLICT (investigation_id, fingerprint) DO UPDATE SET
                    status = EXCLUDED.status,
                    value = EXCLUDED.value,
                    verified_at = CASE
                        WHEN EXCLUDED.status IN (
                            'SUPPORTED', 'PARTIALLY_SUPPORTED', 'CONTRADICTED'
                        ) THEN now()
                        ELSE claims.verified_at
                    END
                RETURNING id
                """
            ),
            {
                "investigation_id": investigation_id,
                "entity_id": entity_id,
                "predicate": predicate,
                "value": _canonical_json(json_value),
                "status": ClaimStatus.SUPPORTED.value,
                "fingerprint": fingerprint,
            },
        )
    ).mappings().one()
    claim_id = row["id"]
    await session.execute(
        text(
            """
            INSERT INTO claim_evidence (claim_id, evidence_id, relation)
            VALUES (:claim_id, :evidence_id, 'supports')
            ON CONFLICT (claim_id, evidence_id, relation) DO NOTHING
            """
        ),
        {"claim_id": claim_id, "evidence_id": evidence_id},
    )
    return claim_id


async def persist_brreg_organization(
    session: AsyncSession,
    investigation_id: UUID,
    record: SourceRecord,
    organization: BrregOrganization,
) -> BrregIngestResult:
    await _ensure_source(session)
    document_id = await _upsert_document(session, record)
    await _attach_document(session, investigation_id, document_id)
    evidence_id = await _root_evidence(session, document_id, organization)
    entity_id = await _upsert_entity(session, organization)
    await _attach_entity(session, investigation_id, entity_id)

    claim_ids = [
        await _upsert_claim(
            session,
            investigation_id,
            entity_id,
            predicate,
            value,
            evidence_id,
        )
        for predicate, value in _claims_for_organization(organization)
    ]

    await session.execute(
        text(
            """
            UPDATE investigations
            SET status = 'ACTIVE', updated_at = now()
            WHERE id = :investigation_id
            """
        ),
        {"investigation_id": investigation_id},
    )

    return BrregIngestResult(
        investigation_id=investigation_id,
        entity_id=entity_id,
        document_id=document_id,
        evidence_id=evidence_id,
        claim_ids=claim_ids,
        organization=organization,
    )
