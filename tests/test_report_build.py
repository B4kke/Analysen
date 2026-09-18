"""Pure unit tests for the deterministic report-JSON builder (AQ-027 slice).

No database: covers the Norwegian outcome mapping, citation assembly from
stub rows (including stale-hash skipping), UNVERIFIED_LEAD exclusion,
unverified-lead shaping and context-entity shaping.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from apps.api.app.domain.models import ClaimStatus
from apps.api.app.services import report_build as rb


def _citation_row(**overrides):
    row = {
        "evidence_id": uuid4(),
        "document_id": uuid4(),
        "source_id": "brreg",
        "excerpt": "Registrert i Brønnøysund",
        "canonical_url": "https://example.invalid/enheter/974760673",
        "original_url": "https://example.invalid/enheter/974760673?raw=1",
        "fetched_at": datetime.now(UTC),
        "sha256": "0" * 64,
    }
    row.update(overrides)
    return row


def test_outcome_mapping_covers_all_five_section_states() -> None:
    assert rb.norwegian_outcome_to_coverage_status("Undersøkt") == "UNDERSØKT"
    assert (
        rb.norwegian_outcome_to_coverage_status("Undersøkt med mangler")
        == "UNDERSØKT_MED_GAPS"
    )
    assert rb.norwegian_outcome_to_coverage_status("Ikke undersøkt") == "IKKE_UNDERSØKT"
    assert (
        rb.norwegian_outcome_to_coverage_status("Utilgjengelig")
        == "BLOKKERT_UTILGJENGELIG"
    )
    assert rb.norwegian_outcome_to_coverage_status("Ikke valgt") == "IKKE_VALGT"


def test_outcome_mapping_rejects_unknown_state() -> None:
    with pytest.raises(ValueError, match="unknown report section outcome"):
        rb.norwegian_outcome_to_coverage_status("Delvis magi")


def test_invert_report_sections_maps_module_to_norwegian_outcome() -> None:
    sections = {
        "Undersøkt": [{"module": "WEB_MEDIA"}],
        "Undersøkt med mangler": [],
        "Ikke undersøkt": [],
        "Utilgjengelig": [],
        "Ikke valgt": [{"module": "SANCTIONS"}],
    }
    assert rb.invert_report_sections(sections) == {
        "WEB_MEDIA": "Undersøkt",
        "SANCTIONS": "Ikke valgt",
    }


@pytest.mark.parametrize(
    "status",
    [
        ClaimStatus.SUPPORTED,
        ClaimStatus.PARTIALLY_SUPPORTED,
        ClaimStatus.CONTRADICTED,
        ClaimStatus.INSUFFICIENT_EVIDENCE,
        "SUPPORTED",
        "INSUFFICIENT_EVIDENCE",
    ],
)
def test_decided_claim_statuses_are_reportable(status) -> None:
    assert rb.is_reportable_claim_status(status) is True


@pytest.mark.parametrize("status", [ClaimStatus.UNVERIFIED_LEAD, "UNVERIFIED_LEAD", "NOPE"])
def test_unverified_lead_and_unknown_statuses_are_excluded(status) -> None:
    assert rb.is_reportable_claim_status(status) is False


def test_citation_assembly_preserves_order_and_skips_stale_hash() -> None:
    claim_id = uuid4()
    rows_by_hash = {"h1": _citation_row(), "h2": _citation_row()}
    citations = rb.assemble_citations_for_hashes(
        claim_id, ["h1", "stale-hash", "h2"], rows_by_hash
    )
    assert len(citations) == 2
    assert all(citation.claim_id == claim_id for citation in citations)
    assert citations[0].evidence_id == rows_by_hash["h1"]["evidence_id"]
    assert citations[1].evidence_id == rows_by_hash["h2"]["evidence_id"]


def test_citation_carries_provenance_fields() -> None:
    claim_id = uuid4()
    row = _citation_row()
    citation = rb.build_citation_from_row(claim_id, row)
    assert citation.evidence_id == row["evidence_id"]
    assert citation.document_id == row["document_id"]
    assert citation.source_id == "brreg"
    assert citation.excerpt == row["excerpt"]
    assert citation.url == row["canonical_url"]
    assert citation.fetched_at == row["fetched_at"]
    assert citation.sha256 == row["sha256"]


def test_citation_falls_back_to_original_url() -> None:
    citation = rb.build_citation_from_row(uuid4(), _citation_row(canonical_url=None))
    assert citation.url == "https://example.invalid/enheter/974760673?raw=1"


def test_citation_without_any_url_has_none_url() -> None:
    row = _citation_row(canonical_url=None, original_url=None)
    assert rb.build_citation_from_row(uuid4(), row).url is None


def test_context_entity_shows_name_and_schema_only() -> None:
    entity = rb.build_context_entity_from_row(
        {"canonical_name": "Kontekst AS", "schema": "Company"}
    )
    assert entity.name == "Kontekst AS"
    assert entity.entity_schema == "Company"
    assert entity.relation is None


def test_context_entity_rejects_missing_schema() -> None:
    with pytest.raises(ValueError, match="schema"):
        rb.build_context_entity_from_row({"canonical_name": "Kontekst AS"})


def test_pending_lead_row_becomes_unverified_lead() -> None:
    lead = rb.build_unverified_lead_from_row(
        {"information_need": "Trenger organisasjonsnummer", "reason": "Svak kilde"}
    )
    assert lead is not None
    assert lead.predicate is None
    assert lead.information_need == "Trenger organisasjonsnummer"
    assert lead.reason == "Svak kilde"


@pytest.mark.parametrize("row", [{}, {"information_need": None}, {"information_need": "  "}])
def test_lead_row_without_information_need_is_skipped(row) -> None:
    assert rb.build_unverified_lead_from_row(row) is None
