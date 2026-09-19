"""Pure unit tests for the deterministic report-JSON builder (AQ-027 slice).

No database: covers the Norwegian outcome mapping, citation assembly from
stub rows (including stale-hash skipping), UNVERIFIED_LEAD exclusion,
unverified-lead shaping, context-entity shaping and conservative media
mention mapping (AQ-031): full/partial/unavailable availability, missing
fields staying None and unknown values failing closed.
"""

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from apps.api.app.domain.models import ClaimStatus
from apps.api.app.domain.nb_media import NBTextAvailability
from apps.api.app.domain.report import MediaMention, ReportDocument
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


# ---------------------------------------------------------------------------
# Media mention mapping (AQ-031, Nasjonalbiblioteket)
# ---------------------------------------------------------------------------


def _media_row(**overrides):
    row = {
        "id": uuid4(),
        "investigation_id": uuid4(),
        "target_query": "Ola Nordmann",
        "publication": "Hadeland",
        "published_at": date(2007, 8, 6),
        "page_number": 23,
        "issue_urn": "URN:NBN:no-nb_digavis_hadeland_null_hadeland_20070806",
        "page_urn": "URN:NBN:no-nb_digavis_hadeland_null_hadeland_20070806_23",
        "headline": "Overskrift fra avis",
        "summary": "Sammendrag fra avis",
        "text_excerpt": "… <em>Ola Nordmann</em> …",
        "text_availability": "PARTIAL_CONTEXT",
        "identity_state": "UNRESOLVED",
        "source_url": "https://www.nb.no/items/URN:NBN:no-nb_digavis_hadeland_null_hadeland_20070806",
        "access_class": "PUBLIC_VIEW_ONLY",
        "license_code": "CC0",
        "image_document_id": uuid4(),
        "image_embeddable": False,
        "created_at": datetime.now(UTC),
    }
    row.update(overrides)
    return row


def test_media_mention_row_maps_full_report_contract() -> None:
    row = _media_row(text_availability="FULL", image_embeddable=True)
    mention = rb.build_media_mention_from_row(row)
    assert mention.publication == "Hadeland"
    assert mention.published_at == date(2007, 8, 6)
    assert mention.page_number == 23
    assert mention.headline == "Overskrift fra avis"
    assert mention.summary == "Sammendrag fra avis"
    assert mention.text_excerpt == "… <em>Ola Nordmann</em> …"
    assert mention.text_availability == NBTextAvailability.FULL
    assert mention.identity_state == "UNRESOLVED"
    assert mention.issue_urn == row["issue_urn"]
    assert mention.page_urn == row["page_urn"]
    assert mention.source_url == row["source_url"]
    assert mention.access_class == "PUBLIC_VIEW_ONLY"
    assert mention.license_code == "CC0"
    assert mention.image_document_id == row["image_document_id"]
    assert mention.image_embeddable is True
    assert mention.target_query == "Ola Nordmann"


def test_media_mention_partial_context_maps_as_partial() -> None:
    mention = rb.build_media_mention_from_row(_media_row(text_availability="PARTIAL_CONTEXT"))
    assert mention.text_availability == NBTextAvailability.PARTIAL_CONTEXT
    assert mention.text_excerpt is not None


def test_media_mention_unavailable_row_keeps_content_none() -> None:
    row = _media_row(
        text_availability="UNAVAILABLE", headline=None, summary=None, text_excerpt=None
    )
    mention = rb.build_media_mention_from_row(row)
    assert mention.text_availability == NBTextAvailability.UNAVAILABLE
    assert mention.headline is None
    assert mention.summary is None
    assert mention.text_excerpt is None
    # Metadata and locators still flow through.
    assert mention.publication == "Hadeland"
    assert mention.page_urn == row["page_urn"]


@pytest.mark.parametrize("value", [None, "", "MAGIC", "FULL_TEXT"])
def test_media_mention_unknown_availability_fails_closed_to_unavailable(value) -> None:
    mention = rb.build_media_mention_from_row(_media_row(text_availability=value))
    assert mention.text_availability == NBTextAvailability.UNAVAILABLE


def test_media_mention_conservative_none_mapping() -> None:
    row = _media_row(
        publication=None,
        published_at=None,
        page_number=None,
        headline=None,
        summary=None,
        text_excerpt=None,
        text_availability=None,
        identity_state=None,
        issue_urn=None,
        page_urn=None,
        source_url=None,
        access_class=None,
        license_code=None,
        image_document_id=None,
        target_query=None,
    )
    mention = rb.build_media_mention_from_row(row)
    assert mention.publication is None
    assert mention.published_at is None
    assert mention.page_number is None
    assert mention.headline is None
    assert mention.summary is None
    assert mention.text_excerpt is None
    assert mention.identity_state is None
    assert mention.issue_urn is None
    assert mention.page_urn is None
    assert mention.source_url is None
    assert mention.access_class is None
    assert mention.license_code is None
    assert mention.image_document_id is None
    assert mention.target_query is None
    # Nothing is fabricated: availability falls back to the conservative
    # DB default and embedding stays False.
    assert mention.text_availability == NBTextAvailability.UNAVAILABLE
    assert mention.image_embeddable is False


def test_media_mention_datetime_published_at_is_dropped_not_coerced() -> None:
    # published_at is a date in the report contract; a datetime is dropped.
    mention = rb.build_media_mention_from_row(
        _media_row(published_at=datetime(2026, 1, 15, 12, 0, 0))
    )
    assert mention.published_at is None


def test_media_mention_non_string_content_stays_none() -> None:
    mention = rb.build_media_mention_from_row(_media_row(headline=123, publication=45.5))
    assert mention.headline is None
    assert mention.publication is None


def test_media_mention_image_document_id_requires_uuid() -> None:
    assert rb.build_media_mention_from_row(
        _media_row(image_document_id="not-a-uuid")
    ).image_document_id is None
    document_id = UUID(int=42)
    assert rb.build_media_mention_from_row(
        _media_row(image_document_id=document_id)
    ).image_document_id == document_id


def test_media_mention_list_mapping_over_empty_rows_is_empty() -> None:
    rows: list[dict[str, Any]] = []
    assert [rb.build_media_mention_from_row(row) for row in rows] == []


def test_media_mention_without_citations_gets_empty_list() -> None:
    mention = rb.build_media_mention_from_row(_media_row())
    assert mention.citations == []


def test_media_mention_carries_provided_citations_unchanged() -> None:
    from apps.api.app.domain.report import ReportCitation

    citation = ReportCitation(
        claim_id=None,
        evidence_id=uuid4(),
        document_id=uuid4(),
        source_id="nb_catalog",
        excerpt="… kontekst …",
        url="nb:URN:NBN:page",
        fetched_at=None,
        sha256="ab" * 32,
    )
    mention = rb.build_media_mention_from_row(_media_row(), [citation])
    assert mention.citations == [citation]


def test_build_mention_citation_maps_evidence_row_without_claim() -> None:
    evidence_id = uuid4()
    document_id = uuid4()
    citation = rb.build_mention_citation(
        {
            "evidence_id": evidence_id,
            "document_id": document_id,
            "source_id": "nb_catalog",
            "excerpt": "… kontekst …",
            "canonical_url": "nb:URN:NBN:page",
            "original_url": None,
            "fetched_at": None,
            "sha256": "cd" * 32,
        }
    )
    assert citation.claim_id is None
    assert citation.evidence_id == evidence_id
    assert citation.document_id == document_id
    assert citation.url == "nb:URN:NBN:page"
    assert citation.sha256 == "cd" * 32


def test_media_mention_xywh_anchors_map_verbatim() -> None:
    anchors = ["xywh=1200,800,400,50", "xywh=1250,860,350,45"]
    mention = rb.build_media_mention_from_row(_media_row(xywh_anchors=anchors))
    assert mention.xywh_anchors == anchors


def test_media_mention_missing_anchors_map_to_empty_list() -> None:
    assert rb.build_media_mention_from_row(_media_row()).xywh_anchors == []
    assert rb.build_media_mention_from_row(_media_row(xywh_anchors=None)).xywh_anchors == []


def test_media_mention_non_string_anchors_are_dropped() -> None:
    mention = rb.build_media_mention_from_row(
        _media_row(xywh_anchors=["xywh=1,2,3,4", 42, None, "  "])
    )
    assert mention.xywh_anchors == ["xywh=1,2,3,4"]


def test_report_document_media_mentions_default_empty() -> None:
    document = ReportDocument(
        investigation_id=uuid4(),
        target_name="Tom",
        target_type="person",
        purpose="Tom rapport",
        generated_at=datetime.now(UTC),
        expansion_policy="DIRECT_ONLY",
        max_relation_depth=0,
    )
    assert document.media_mentions == []


def test_media_mention_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        MediaMention.model_validate({"publication": "X", "no_such_field": 1})


def test_media_mention_serializes_availability_as_plain_string() -> None:
    mention = rb.build_media_mention_from_row(_media_row())
    assert mention.model_dump(mode="json")["text_availability"] == "PARTIAL_CONTEXT"
    assert mention.model_dump(mode="json")["published_at"] == "2007-08-06"
