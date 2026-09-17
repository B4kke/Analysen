import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.domain.models import (
    InvestigationClaimRecord,
    InvestigationCreate,
    InvestigationDetail,
    InvestigationEntityRecord,
    InvestigationRecord,
    TargetInput,
)


class InvestigationNotFound(LookupError):
    pass


async def create_investigation(
    session: AsyncSession,
    request: InvestigationCreate,
) -> InvestigationRecord:
    row = (
        await session.execute(
            text(
                """
                INSERT INTO investigations (
                    target_type,
                    target_input,
                    purpose,
                    legal_basis_note
                )
                VALUES (
                    :target_type,
                    CAST(:target_input AS jsonb),
                    :purpose,
                    :legal_basis_note
                )
                RETURNING
                    id, target_input, purpose, legal_basis_note,
                    status, created_at, updated_at
                """
            ),
            {
                "target_type": request.target.type.value,
                "target_input": json.dumps(request.target.model_dump(mode="json")),
                "purpose": request.purpose,
                "legal_basis_note": request.legal_basis_note,
            },
        )
    ).mappings().one()

    return InvestigationRecord(
        id=row["id"],
        target=TargetInput.model_validate(row["target_input"]),
        purpose=row["purpose"],
        legal_basis_note=row["legal_basis_note"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def get_investigation(
    session: AsyncSession,
    investigation_id: UUID,
) -> InvestigationDetail:
    row = (
        await session.execute(
            text(
                """
                SELECT id, target_input, purpose, legal_basis_note, status, created_at, updated_at
                FROM investigations
                WHERE id = :investigation_id
                """
            ),
            {"investigation_id": investigation_id},
        )
    ).mappings().one_or_none()
    if row is None:
        raise InvestigationNotFound(str(investigation_id))

    entity_rows = (
        await session.execute(
            text(
                """
                SELECT e.id, e.schema, e.canonical_name, e.attributes, e.resolution_state
                FROM investigation_entities ie
                JOIN entities e ON e.id = ie.entity_id
                WHERE ie.investigation_id = :investigation_id
                ORDER BY ie.discovered_at, e.canonical_name NULLS LAST
                """
            ),
            {"investigation_id": investigation_id},
        )
    ).mappings().all()

    claim_rows = (
        await session.execute(
            text(
                """
                SELECT id, subject_entity_id, predicate, value, status, created_at
                FROM claims
                WHERE investigation_id = :investigation_id
                ORDER BY created_at, predicate
                """
            ),
            {"investigation_id": investigation_id},
        )
    ).mappings().all()

    return InvestigationDetail(
        id=row["id"],
        target=TargetInput.model_validate(row["target_input"]),
        purpose=row["purpose"],
        legal_basis_note=row["legal_basis_note"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        entities=[InvestigationEntityRecord.model_validate(item) for item in entity_rows],
        claims=[InvestigationClaimRecord.model_validate(item) for item in claim_rows],
    )


async def mark_investigation_active(session: AsyncSession, investigation_id: UUID) -> None:
    result = await session.execute(
        text(
            """
            UPDATE investigations
            SET status = 'ACTIVE', updated_at = now()
            WHERE id = :investigation_id
            """
        ),
        {"investigation_id": investigation_id},
    )
    if result.rowcount == 0:
        raise InvestigationNotFound(str(investigation_id))
