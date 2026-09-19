"""Deterministic evidence-entailment verifier (AQ-026).

Pure rules over stored rows. No model calls: the verdict contract from
``prompts/verifier.md`` (SUPPORTED / PARTIALLY_SUPPORTED / CONTRADICTED /
INSUFFICIENT_EVIDENCE) is implemented here as deterministic entailment over
concrete ``claim_evidence`` links joined against real ``evidence`` rows.

Verdict rules, evaluated in order:

1. any ``contradicts`` link to a real evidence row -> CONTRADICTED,
2. any ``supports`` link to a row carrying excerpt or structured content
   -> SUPPORTED (citation gate: a claim can never become SUPPORTED without
   at least one real evidence row),
3. any ``context`` link to a real row -> PARTIALLY_SUPPORTED,
4. otherwise -> INSUFFICIENT_EVIDENCE (UNVERIFIED_LEAD is a valid starting
   point but never a verdict output).

Missing information is returned as a typed need that the caller routes
through the trigger/scope gate; it is never a direct search command.
Contradiction handling seeks targeted disconfirmation (paired claims), not
broad expansion. The rationale is a plain human-readable string and is
never itself evidence.
"""

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.domain.models import ClaimStatus, VerificationResult
from apps.api.app.repositories import claims_evidence
from apps.api.app.repositories import investigations as repository


def _has_content(excerpt: Any, structured_value: Any) -> bool:
    """Whether an evidence row carries quotable or structured content."""
    if isinstance(excerpt, str) and excerpt.strip():
        return True
    if structured_value is None:
        return False
    return not (
        isinstance(structured_value, (dict, list, str)) and len(structured_value) == 0
    )


def _partition_links(
    links: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
) -> tuple[list[Any], list[Any], list[Any], list[Any]]:
    """Split links into (supporting, usable_supporting, contradicting, context).

    Only links that resolve to a real evidence row are kept: orphan ids and
    unknown relation values are ignored so they can never ground a verdict.
    Duplicate (evidence, relation) pairs collapse to first-seen order.
    """
    lookup: dict[Any, dict[str, Any]] = {}
    for entry in evidence_rows:
        lookup.setdefault(entry.get("id"), entry)
        lookup.setdefault(str(entry.get("id")), entry)
    supporting: list[Any] = []
    usable: list[Any] = []
    contradicting: list[Any] = []
    context: list[Any] = []
    seen: set[tuple[str, str]] = set()
    for link in links:
        evidence_id = link.get("evidence_id")
        relation = link.get("relation")
        marker = (str(evidence_id), str(relation))
        if marker in seen:
            continue
        seen.add(marker)
        row = lookup.get(evidence_id)
        if row is None:
            row = lookup.get(str(evidence_id))
        if row is None:
            continue
        if relation == "supports":
            supporting.append(evidence_id)
            if _has_content(row.get("excerpt"), row.get("structured_value")):
                usable.append(evidence_id)
        elif relation == "contradicts":
            contradicting.append(evidence_id)
        elif relation == "context":
            context.append(evidence_id)
        # Unknown relations are ignored: they fail closed to INSUFFICIENT_EVIDENCE.
    return supporting, usable, contradicting, context


def decide_verdict(
    links: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
) -> ClaimStatus:
    """Pure verdict ordering over stub-friendly dicts; no database access.

    ``links`` are ``{"evidence_id": ..., "relation": ...}`` mappings and
    ``evidence_rows`` are ``{"id": ..., "excerpt": ..., "structured_value": ...}``
    mappings. Always returns one of the four verdict outcomes, never
    UNVERIFIED_LEAD.
    """
    _supporting, usable, contradicting, context = _partition_links(links, evidence_rows)
    if contradicting:
        return ClaimStatus.CONTRADICTED
    if usable:
        return ClaimStatus.SUPPORTED
    if context:
        return ClaimStatus.PARTIALLY_SUPPORTED
    return ClaimStatus.INSUFFICIENT_EVIDENCE


def _canonical_value(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        )
    except (TypeError, ValueError):
        return str(value)


def find_contradiction_pairs(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pure contradiction detection over claim dicts; no database access.

    Pairs share a non-null subject entity id and equal predicate but carry
    different canonical values, with at least one side SUPPORTED or
    PARTIALLY_SUPPORTED. NULL subjects never pair. Output is sorted
    deterministically by predicate, subject, then claim ids.
    """
    qualifying = {ClaimStatus.SUPPORTED.value, ClaimStatus.PARTIALLY_SUPPORTED.value}
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for claim in claims:
        subject = claim.get("subject_entity_id")
        if subject is None:
            continue
        groups.setdefault((str(subject), str(claim.get("predicate"))), []).append(claim)
    pairs: list[dict[str, Any]] = []
    for members in groups.values():
        for index, first in enumerate(members):
            for second in members[index + 1 :]:
                if _canonical_value(first.get("value")) == _canonical_value(
                    second.get("value")
                ):
                    continue
                first_status = str(first.get("status"))
                second_status = str(second.get("status"))
                if first_status not in qualifying and second_status not in qualifying:
                    continue
                low, high = (
                    (first["id"], second["id"])
                    if str(first["id"]) <= str(second["id"])
                    else (second["id"], first["id"])
                )
                pairs.append(
                    {
                        "claim_a_id": low,
                        "claim_b_id": high,
                        "predicate": str(first.get("predicate")),
                        "subject_entity_id": first.get("subject_entity_id"),
                    }
                )
    pairs.sort(
        key=lambda item: (
            str(item["predicate"]),
            str(item["subject_entity_id"]),
            str(item["claim_a_id"]),
            str(item["claim_b_id"]),
        )
    )
    return pairs


def missing_information_need(
    claim: dict[str, Any], evidence_count: int
) -> dict[str, Any] | None:
    """Typed missing-information need for a claim without usable evidence.

    Returns None when the claim has usable evidence. The returned dict is a
    routing need for the trigger/scope gate, never a search command.
    """
    if evidence_count > 0:
        return None
    predicate = claim.get("predicate", "unknown")
    subject = claim.get("subject_entity_id")
    return {
        "predicate": predicate,
        "information_need": f"Independent evidence for {predicate} on {subject}",
        "reason": "verifier found no usable evidence",
    }


def _rationale(
    status: ClaimStatus,
    *,
    usable: int,
    supporting: int,
    contradicting: int,
    context: int,
) -> str:
    """Human-readable rationale naming the evidence counts behind a verdict."""
    if status == ClaimStatus.CONTRADICTED:
        return (
            f"verdict CONTRADICTED: {contradicting} contradicting evidence row(s) "
            f"outweigh {usable} usable supporting row(s)"
        )
    if status == ClaimStatus.SUPPORTED:
        return (
            f"verdict SUPPORTED: {usable} supporting evidence row(s) carry "
            "excerpt or structured content"
        )
    if status == ClaimStatus.PARTIALLY_SUPPORTED:
        return (
            f"verdict PARTIALLY_SUPPORTED: {context} context evidence row(s) linked, "
            "no contradicting rows and no usable supporting content"
        )
    return (
        "verdict INSUFFICIENT_EVIDENCE: no usable supporting content "
        f"({supporting} supporting, {context} context, "
        f"{contradicting} contradicting rows linked)"
    )


async def verify_claim(
    session: AsyncSession, investigation_id: UUID, claim_id: UUID
) -> VerificationResult:
    """Recompute one claim's verdict from its stored evidence links.

    Loads the claim, joins ``claim_evidence`` against real ``evidence`` rows,
    applies the deterministic verdict rules, persists the new status in place
    via ``claims_evidence.upsert_claim`` (same fingerprint), audits the
    decision as VERIFICATION_DECIDED, and returns the schema-validated result.

    Raises LookupError for an unknown claim id or a claim owned by another
    investigation (callers map this to 404). Transitions from any stored
    status to one of the four verdict outcomes are allowed; UNVERIFIED_LEAD
    is a valid starting point but never an output. No model calls.
    """
    claim = await claims_evidence.get_claim(session, claim_id)
    if claim is None or str(claim.get("investigation_id")) != str(investigation_id):
        raise LookupError(f"unknown claim {claim_id} for investigation {investigation_id}")
    previous_status = str(claim.get("status"))

    link_rows = (
        await session.execute(
            text(
                "SELECT evidence_id, relation FROM claim_evidence "
                "WHERE claim_id = :cid ORDER BY evidence_id, relation"
            ),
            {"cid": claim_id},
        )
    ).mappings().all()
    links = [dict(row) for row in link_rows]

    evidence_rows = (
        await session.execute(
            text(
                "SELECT e.id AS id, e.excerpt AS excerpt, "
                "e.structured_value AS structured_value "
                "FROM evidence e JOIN claim_evidence ce ON ce.evidence_id = e.id "
                "WHERE ce.claim_id = :cid"
            ),
            {"cid": claim_id},
        )
    ).mappings().all()
    rows = [dict(row) for row in evidence_rows]

    status = decide_verdict(links, rows)
    supporting, usable, contradicting, context = _partition_links(links, rows)

    if status == ClaimStatus.SUPPORTED:
        role, persist_ids = "SUPPORTS", supporting
    elif status == ClaimStatus.CONTRADICTED:
        role, persist_ids = "CONTRADICTS", contradicting
    elif status == ClaimStatus.PARTIALLY_SUPPORTED:
        # Context-only evidence is the honest backing for a partial verdict:
        # the repository accepts PARTIAL-backed PARTIALLY_SUPPORTED rows and
        # stores them with the context relation, preserving provenance.
        role, persist_ids = "PARTIAL", context
    else:
        role, persist_ids = "SUPPORTS", []

    await claims_evidence.upsert_claim(
        session,
        investigation_id,
        claim.get("subject_entity_id"),
        str(claim.get("predicate")),
        claim.get("value"),
        status.value,
        list(persist_ids),
        role,
    )
    refreshed = await claims_evidence.get_claim(session, claim_id)
    verified_at = (refreshed or {}).get("verified_at") or datetime.now(UTC)

    await repository._audit(
        session,
        investigation_id,
        "VERIFICATION_DECIDED",
        {
            "claim_id": str(claim_id),
            "from": previous_status,
            "to": status.value,
            "supporting": [str(item) for item in supporting],
            "contradicting": [str(item) for item in contradicting],
        },
    )

    return VerificationResult(
        status=status,
        rationale=_rationale(
            status,
            usable=len(usable),
            supporting=len(supporting),
            contradicting=len(contradicting),
            context=len(context),
        ),
        supporting_evidence_ids=list(supporting),
        contradicting_evidence_ids=list(contradicting),
        verified_at=verified_at,
    )


async def detect_contradictions(
    session: AsyncSession, investigation_id: UUID
) -> list[dict[str, Any]]:
    """Find contradicting claim pairs in one investigation.

    Read-only: never writes. Pairs share a non-null subject entity id and
    equal predicate with different canonical values, where at least one side
    is SUPPORTED or PARTIALLY_SUPPORTED. Results are sorted deterministically.
    """
    rows = (
        await session.execute(
            text(
                "SELECT id, subject_entity_id, predicate, value, status "
                "FROM claims WHERE investigation_id = :iid"
            ),
            {"iid": investigation_id},
        )
    ).mappings().all()
    return find_contradiction_pairs([dict(row) for row in rows])
