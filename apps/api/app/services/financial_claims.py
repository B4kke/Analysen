"""Deterministic mapping from extracted financial analysis to claims (AQ-019 slice).

Pure translation layer: :mod:`pdf_extraction` computes ratios, year-over-year
changes, auditor notes and going-concern flags; ``build_financial_claims``
turns those outputs into persistable claim dicts, and
``persist_financial_claims`` stores them via
:mod:`apps.api.app.repositories.claims_evidence`. No LLM, no heuristics
beyond the mapping rules below.
"""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.repositories import claims_evidence


def build_financial_claims(
    *,
    ratios: dict[str, float],
    year_over_year: dict[str, dict[str, float]],
    auditor_notes: list[str],
    going_concern: bool | None,
) -> list[dict[str, Any]]:
    """Build persistable claim dicts from extracted financial analysis.

    Rules: one claim per ratio, one per YoY change, one per auditor note, and
    at most one going-concern claim (only when ``going_concern is True``).
    ``None`` means "not mentioned" and never emits a negative claim.
    """
    claims: list[dict[str, Any]] = []
    for name in sorted(ratios):
        claims.append(
            {
                "predicate": f"financial.ratio.{name}",
                "value": {"value": ratios[name]},
                "status": "SUPPORTED",
                "evidence_role": "SUPPORTS",
            }
        )
    for metric in sorted(year_over_year):
        for period in sorted(year_over_year[metric]):
            claims.append(
                {
                    "predicate": f"financial.yoy.{metric}",
                    "value": {"period": period, "change": year_over_year[metric][period]},
                    "status": "SUPPORTED",
                    "evidence_role": "SUPPORTS",
                }
            )
    for note in auditor_notes:
        claims.append(
            {
                "predicate": "financial.auditor_note",
                "value": {"note": note},
                "status": "SUPPORTED",
                "evidence_role": "SUPPORTS",
            }
        )
    if going_concern is True:
        claims.append(
            {
                "predicate": "financial.going_concern_discussed",
                "value": {"discussed": True},
                "status": "SUPPORTED",
                "evidence_role": "SUPPORTS",
            }
        )
    return claims


async def persist_financial_claims(
    session: AsyncSession,
    investigation_id: UUID,
    subject_entity_id: UUID | None,
    claims: list[dict[str, Any]],
    evidence_ids: list[UUID],
) -> list[UUID]:
    """Persist pre-built claim dicts via ``claims_evidence.upsert_claim``."""
    claim_ids: list[UUID] = []
    for claim in claims:
        claim_id = await claims_evidence.upsert_claim(
            session,
            investigation_id,
            subject_entity_id,
            claim["predicate"],
            claim["value"],
            claim.get("status", "SUPPORTED"),
            evidence_ids,
            claim.get("evidence_role", "SUPPORTS"),
        )
        claim_ids.append(claim_id)
    return claim_ids
