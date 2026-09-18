"""Deterministic report-JSON builder (AQ-027 slice).

No LLM, no rendering. Assembles a :class:`ReportDocument` from stored rows:
verified claims with per-claim citations, pending (open) leads, context-only
entities and per-module coverage.

Contract notes:

- Claims still in ``UNVERIFIED_LEAD`` status are skipped here. Open work is
  reported through the pending-leads list, never as findings.
- Only ``PENDING`` leads become :class:`UnverifiedLead` rows. Decided work
  (``BLOCKED``/completed leads) already shows up in coverage/findings, so the
  report does not list lead graveyards.
- A citation whose evidence hash no longer resolves to a stored row (stale
  hash) is skipped rather than failing the whole build.
- Context-only entities appear by name and schema only, never as researched
  subjects.
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.domain.models import ClaimStatus
from apps.api.app.domain.report import (
    ContextEntity,
    CoverageEntry,
    ReportCitation,
    ReportDocument,
    ReportFinding,
    UnverifiedLead,
)
from apps.api.app.domain.scope import ScopeSettings
from apps.api.app.repositories import claims_evidence as claims_repo
from apps.api.app.repositories import investigations as investigations_repo
from apps.api.app.services.report_sections import report_sections

#: Claim statuses that may appear as report findings. UNVERIFIED_LEAD is
#: deliberately absent: open leads are reported via ``unverified_leads``.
_REPORTABLE_CLAIM_STATUSES = frozenset(
    {
        ClaimStatus.SUPPORTED,
        ClaimStatus.PARTIALLY_SUPPORTED,
        ClaimStatus.CONTRADICTED,
        ClaimStatus.INSUFFICIENT_EVIDENCE,
    }
)

# Report sections speak Norwegian ("Undersøkt", ...); CoverageEntry.outcome
# stores the ASCII code ("UNDERSØKT", ...) so API/mobile clients can match on
# a stable value without parsing Norwegian prose. This dict is the single
# translation point between the two vocabularies.
_NORWEGIAN_OUTCOME_TO_COVERAGE_STATUS = {
    "Undersøkt": "UNDERSØKT",
    "Undersøkt med mangler": "UNDERSØKT_MED_GAPS",
    "Ikke undersøkt": "IKKE_UNDERSØKT",
    "Utilgjengelig": "BLOKKERT_UTILGJENGELIG",
    "Ikke valgt": "IKKE_VALGT",
}


def is_reportable_claim_status(status: str | ClaimStatus) -> bool:
    """True when a claim status may appear as a finding.

    ``UNVERIFIED_LEAD`` (and any unknown status string) returns False: such
    claims are open work, not findings.
    """
    try:
        parsed = status if isinstance(status, ClaimStatus) else ClaimStatus(status)
    except ValueError:
        return False
    return parsed in _REPORTABLE_CLAIM_STATUSES


def norwegian_outcome_to_coverage_status(outcome: str) -> str:
    """Translate one Norwegian section outcome to its coverage status code."""
    try:
        return _NORWEGIAN_OUTCOME_TO_COVERAGE_STATUS[outcome]
    except KeyError as exc:
        raise ValueError(f"unknown report section outcome: {outcome!r}") from exc


def invert_report_sections(
    sections: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, str]:
    """Invert ``report_sections()`` output to module name -> Norwegian outcome."""
    inverted: dict[str, str] = {}
    for outcome, entries in sections.items():
        for entry in entries:
            inverted[str(entry["module"])] = outcome
    return inverted


def build_citation_from_row(claim_id: UUID, row: Mapping[str, Any]) -> ReportCitation:
    """Assemble one citation from an evidence+document join row.

    The row carries ``evidence_id``, ``document_id``, ``source_id``,
    ``excerpt``, ``canonical_url``/``original_url``, ``fetched_at`` and
    ``sha256``. The canonical URL wins when both URLs are present.
    """
    url = row.get("canonical_url") or row.get("original_url") or None
    return ReportCitation(
        claim_id=claim_id,
        evidence_id=row.get("evidence_id"),
        document_id=row.get("document_id"),
        source_id=row.get("source_id"),
        excerpt=row.get("excerpt"),
        url=url,
        fetched_at=row.get("fetched_at"),
        sha256=row.get("sha256"),
    )


def assemble_citations_for_hashes(
    claim_id: UUID,
    hashes: Sequence[str],
    rows_by_hash: Mapping[str, Mapping[str, Any]],
) -> list[ReportCitation]:
    """Assemble citations in claim order, skipping stale hashes.

    A hash with no stored evidence/document row is stale provenance and is
    skipped so one dangling link cannot fail the whole report.
    """
    citations: list[ReportCitation] = []
    for digest in hashes:
        row = rows_by_hash.get(digest)
        if row is None:
            continue
        citations.append(build_citation_from_row(claim_id, row))
    return citations


def build_context_entity_from_row(row: Mapping[str, Any]) -> ContextEntity:
    """Shape one context-only entity: name and schema, never a background check."""
    name = row.get("canonical_name", row.get("name"))
    schema = row.get("schema")
    if not isinstance(schema, str) or not schema:
        raise ValueError("context entity rows require a schema string")
    return ContextEntity(
        name=name if isinstance(name, str) else None,
        entity_schema=schema,
        relation=None,
    )


def build_unverified_lead_from_row(row: Mapping[str, Any]) -> UnverifiedLead | None:
    """Shape one pending lead row, or None when it carries no information need.

    The report lists open information needs; a pending row without one has
    nothing to show and is skipped.
    """
    need = row.get("information_need")
    if not isinstance(need, str) or not need.strip():
        return None
    reason = row.get("reason")
    return UnverifiedLead(
        predicate=None,
        information_need=need,
        reason=reason if isinstance(reason, str) and reason else None,
    )


async def _fetch_subject_names(
    session: AsyncSession, subject_ids: set[UUID]
) -> dict[UUID, str | None]:
    """Resolve entity ids to canonical names; missing entities map to None."""
    names: dict[UUID, str | None] = {}
    for subject_id in subject_ids:
        row = (
            await session.execute(
                text("SELECT canonical_name FROM entities WHERE id = :eid"),
                {"eid": subject_id},
            )
        ).mappings().one_or_none()
        if row is not None:
            names[subject_id] = row["canonical_name"]
    return names


async def _fetch_citation_rows(
    session: AsyncSession, hashes: Sequence[str]
) -> dict[str, dict[str, Any]]:
    """Look up evidence+document rows by content hash; stale hashes are absent.

    One equality query per distinct hash keeps the lookup driver-portable and
    lets a missing row simply stay out of the result instead of failing.
    """
    rows: dict[str, dict[str, Any]] = {}
    for digest in dict.fromkeys(hashes):
        row = (
            await session.execute(
                text("""
                    SELECT e.content_hash, e.id AS evidence_id, e.document_id,
                           e.excerpt, d.source_id, d.canonical_url,
                           d.original_url, d.fetched_at, d.sha256
                    FROM evidence e JOIN documents d ON d.id = e.document_id
                    WHERE e.content_hash = :ch
                    LIMIT 1
                """),
                {"ch": digest},
            )
        ).mappings().one_or_none()
        if row is not None:
            rows[digest] = dict(row)
    return rows


async def _fetch_context_entity_rows(
    session: AsyncSession, investigation_id: UUID
) -> list[dict[str, Any]]:
    """Load context-only entities: name and schema, nothing researched."""
    rows = (
        await session.execute(
            text("""
                SELECT e.canonical_name, e.schema
                FROM investigation_entities ie
                JOIN entities e ON e.id = ie.entity_id
                WHERE ie.investigation_id = :iid
                  AND ie.expansion_state = 'CONTEXT_ONLY'
                ORDER BY e.canonical_name NULLS LAST
            """),
            {"iid": investigation_id},
        )
    ).mappings().all()
    return [dict(row) for row in rows]


async def build_report_document(
    session: AsyncSession, investigation_id: UUID
) -> ReportDocument:
    """Build the deterministic report JSON for one investigation.

    Loads the investigation record, module coverage (via ``report_sections()``
    so outcome semantics stay in one place), reportable claims with citations,
    pending leads and context-only entities. Raises ``InvestigationNotFound``
    for an unknown investigation.
    """
    record = await investigations_repo.get_investigation_record(session, investigation_id)
    modules = await investigations_repo.get_modules(session, investigation_id)

    scope = ScopeSettings(
        scope_modules=list(record.scope_modules),
        expansion_policy=record.expansion_policy,
        max_relation_depth=record.max_relation_depth,
    )
    module_outcome = invert_report_sections(report_sections(scope, modules))
    coverage = [
        CoverageEntry(
            module=module.module.value,
            enabled=module.enabled,
            status=module.status.value,
            outcome=norwegian_outcome_to_coverage_status(
                module_outcome[module.module.value]
            ),
            stop_reason=module.stop_reason,
            providers=list(module.coverage.providers),
            query_count=module.coverage.query_count,
            document_count=module.coverage.document_count,
        )
        for module in modules
    ]

    claim_rows = await claims_repo.list_claims_for_investigation(session, investigation_id)
    reportable = [
        row
        for row in claim_rows
        if is_reportable_claim_status(str(row.get("status")))
    ]
    subject_ids = {
        row["subject_entity_id"] for row in reportable if row.get("subject_entity_id")
    }
    subject_names = await _fetch_subject_names(session, set(subject_ids))
    all_hashes = [
        digest
        for row in reportable
        for digest in (row.get("evidence_hashes") or [])
        if isinstance(digest, str) and digest
    ]
    rows_by_hash = await _fetch_citation_rows(session, all_hashes)

    findings: list[ReportFinding] = []
    for row in reportable:
        claim_id = row["id"]
        hashes = [
            digest
            for digest in (row.get("evidence_hashes") or [])
            if isinstance(digest, str) and digest
        ]
        subject_id = row.get("subject_entity_id")
        findings.append(
            ReportFinding(
                predicate=row["predicate"],
                value=row.get("value"),
                status=ClaimStatus(row["status"]),
                subject_name=subject_names.get(subject_id)
                if subject_id is not None
                else None,
                citations=assemble_citations_for_hashes(claim_id, hashes, rows_by_hash),
            )
        )

    lead_rows = await investigations_repo.list_pending_leads(session, investigation_id)
    unverified_leads: list[UnverifiedLead] = []
    for lead_row in lead_rows:
        lead = build_unverified_lead_from_row(lead_row)
        if lead is not None:
            unverified_leads.append(lead)

    context_entities = [
        build_context_entity_from_row(row)
        for row in await _fetch_context_entity_rows(session, investigation_id)
    ]

    return ReportDocument(
        investigation_id=investigation_id,
        target_name=record.target.name,
        target_type=record.target.type.value,
        purpose=record.purpose,
        generated_at=datetime.now(UTC),
        expansion_policy=record.expansion_policy.value,
        max_relation_depth=record.max_relation_depth,
        scope_modules=[module.value for module in record.scope_modules],
        findings=findings,
        unverified_leads=unverified_leads,
        context_entities=context_entities,
        coverage=coverage,
    )
