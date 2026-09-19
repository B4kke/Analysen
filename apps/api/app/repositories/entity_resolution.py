"""Entity resolution candidate persistence and manual review (AQ-022).

The deterministic scorer proposes; a human disposes. Candidates are stored
with their score and negative signals. Manual review may approve a
PROBABLE_MATCH into MATCH or reject into NOT_MATCH; every other transition
is refused so the scorer's states cannot be forged by hand. All decisions
are audited.
"""

import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.repositories.investigations import InvestigationNotFound, _audit


class IllegalResolutionTransition(ValueError):
    """Raised when a manual review transition is not permitted."""


_ALLOWED_MANUAL_TRANSITIONS = frozenset(
    {
        ("PROBABLE_MATCH", "MATCH"),
        ("PROBABLE_MATCH", "NOT_MATCH"),
        ("UNRESOLVED", "NOT_MATCH"),
    }
)


async def upsert_resolution_candidate(
    session: AsyncSession,
    investigation_id: UUID,
    entity_id: UUID,
    candidate_entity_id: UUID,
    match_score: float,
    resolution_status: str,
    negative_signals: list[str],
) -> None:
    """Store or refresh a scorer-produced candidate row."""
    await session.execute(
        text("""
            INSERT INTO entity_resolution_candidates (
                investigation_id, entity_id, candidate_entity_id,
                match_score, resolution_status, negative_signals
            ) VALUES (
                :investigation_id, :entity_id, :candidate_entity_id,
                :match_score, :resolution_status,
                CAST(:negative_signals AS jsonb)
            )
            ON CONFLICT (investigation_id, entity_id, candidate_entity_id)
            DO UPDATE SET
                match_score = EXCLUDED.match_score,
                resolution_status = EXCLUDED.resolution_status,
                negative_signals = EXCLUDED.negative_signals,
                resolved_at = NULL
        """),
        {
            "investigation_id": investigation_id,
            "entity_id": entity_id,
            "candidate_entity_id": candidate_entity_id,
            "match_score": match_score,
            "resolution_status": resolution_status,
            "negative_signals": json.dumps(negative_signals),
        },
    )


async def list_resolution_candidates(
    session: AsyncSession, investigation_id: UUID
) -> list[dict]:
    rows = (
        await session.execute(
            text("""
                SELECT entity_id, candidate_entity_id, match_score,
                    resolution_status, negative_signals, resolved_at
                FROM entity_resolution_candidates
                WHERE investigation_id = :id
                ORDER BY match_score DESC
            """),
            {"id": investigation_id},
        )
    ).mappings().all()
    return [dict(row) for row in rows]


async def review_resolution_candidate(
    session: AsyncSession,
    investigation_id: UUID,
    entity_id: UUID,
    candidate_entity_id: UUID,
    new_status: str,
    reason: str,
) -> dict:
    """Apply a manual review decision with audited, guarded transitions."""
    row = (
        await session.execute(
            text("""
                SELECT resolution_status FROM entity_resolution_candidates
                WHERE investigation_id = :id AND entity_id = :entity_id
                    AND candidate_entity_id = :candidate_id
            """),
            {
                "id": investigation_id,
                "entity_id": entity_id,
                "candidate_id": candidate_entity_id,
            },
        )
    ).mappings().one_or_none()
    if row is None:
        raise InvestigationNotFound(f"{entity_id}/{candidate_entity_id}")
    current = row["resolution_status"]
    if (current, new_status) not in _ALLOWED_MANUAL_TRANSITIONS:
        raise IllegalResolutionTransition(f"{current} -> {new_status} is not permitted")
    await session.execute(
        text("""
            UPDATE entity_resolution_candidates
            SET resolution_status = :new_status, resolved_at = now()
            WHERE investigation_id = :id AND entity_id = :entity_id
                AND candidate_entity_id = :candidate_id
        """),
        {
            "new_status": new_status,
            "id": investigation_id,
            "entity_id": entity_id,
            "candidate_id": candidate_entity_id,
        },
    )
    await _audit(
        session,
        investigation_id,
        "RESOLUTION_REVIEWED",
        {
            "entity_id": str(entity_id),
            "candidate_entity_id": str(candidate_entity_id),
            "from": current,
            "to": new_status,
            "reason": reason,
        },
    )
    return {"from": current, "to": new_status}
