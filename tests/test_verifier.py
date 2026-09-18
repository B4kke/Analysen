"""Deterministic verifier unit tests (AQ-026).

Pure rule-ordering tests over stub claim/evidence dicts; no database access.
Covers verdict ordering, the SUPPORTED citation gate, status-transition
determinism, typed missing-information needs, contradiction pairing, and
schema-invalid/model-failure behaviour at the validation boundary.
"""

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from apps.api.app.domain.models import ClaimStatus, VerificationResult
from apps.api.app.services.verifier import (
    decide_verdict,
    find_contradiction_pairs,
    missing_information_need,
)


def _link(evidence_id, relation):
    return {"evidence_id": evidence_id, "relation": relation}


def _row(evidence_id, excerpt="excerpt text", structured=None):
    return {"id": evidence_id, "excerpt": excerpt, "structured_value": structured}


def test_contradicts_beats_supports() -> None:
    supporting, contradicting = uuid4(), uuid4()
    links = [_link(supporting, "supports"), _link(contradicting, "contradicts")]
    rows = [_row(supporting), _row(contradicting, excerpt=None)]
    assert decide_verdict(links, rows) == ClaimStatus.CONTRADICTED


def test_supports_requires_real_row() -> None:
    orphan = uuid4()
    # A supports link without a backing evidence row can never support.
    assert decide_verdict([_link(orphan, "supports")], []) == (
        ClaimStatus.INSUFFICIENT_EVIDENCE
    )
    unrelated = _row(uuid4())
    assert decide_verdict([_link(orphan, "supports")], [unrelated]) == (
        ClaimStatus.INSUFFICIENT_EVIDENCE
    )


@pytest.mark.parametrize("excerpt", [None, "", "   "])
def test_supports_requires_usable_content(excerpt) -> None:
    evidence_id = uuid4()
    links = [_link(evidence_id, "supports")]
    rows = [_row(evidence_id, excerpt=excerpt, structured=None)]
    assert decide_verdict(links, rows) == ClaimStatus.INSUFFICIENT_EVIDENCE


def test_structured_value_alone_counts_as_content() -> None:
    evidence_id = uuid4()
    links = [_link(evidence_id, "supports")]
    rows = [_row(evidence_id, excerpt=None, structured={"field": "value"})]
    assert decide_verdict(links, rows) == ClaimStatus.SUPPORTED
    empty_structured = [_row(evidence_id, excerpt=None, structured={})]
    assert decide_verdict(links, empty_structured) == ClaimStatus.INSUFFICIENT_EVIDENCE


def test_context_only_is_partial() -> None:
    evidence_id = uuid4()
    links = [_link(evidence_id, "context")]
    assert decide_verdict(links, [_row(evidence_id)]) == ClaimStatus.PARTIALLY_SUPPORTED


def test_empty_links_is_insufficient() -> None:
    assert decide_verdict([], []) == ClaimStatus.INSUFFICIENT_EVIDENCE


def test_unknown_relations_fail_closed() -> None:
    evidence_id = uuid4()
    links = [_link(evidence_id, "irrelevant")]
    assert decide_verdict(links, [_row(evidence_id)]) == ClaimStatus.INSUFFICIENT_EVIDENCE


def test_orphan_contradicts_link_cannot_ground_a_verdict() -> None:
    supporting = uuid4()
    links = [_link(uuid4(), "contradicts"), _link(supporting, "supports")]
    # The orphan contradicts link is ignored; usable supports still decide.
    assert decide_verdict(links, [_row(supporting)]) == ClaimStatus.SUPPORTED


@pytest.mark.parametrize(
    "prior",
    [
        "UNVERIFIED_LEAD",
        "SUPPORTED",
        "PARTIALLY_SUPPORTED",
        "CONTRADICTED",
        "INSUFFICIENT_EVIDENCE",
        "LEGACY_UNKNOWN",
    ],
)
def test_verdict_is_deterministic_regardless_of_prior_status(prior) -> None:
    """Transitions may start from any stored status; only evidence decides."""
    evidence_id = uuid4()
    links = [_link(evidence_id, "supports")]
    rows = [_row(evidence_id)]
    assert decide_verdict(links, rows) == ClaimStatus.SUPPORTED


def test_unverified_lead_is_never_emitted() -> None:
    evidence_id = uuid4()
    configs = [
        ([], []),
        ([_link(evidence_id, "supports")], []),
        ([_link(evidence_id, "supports")], [_row(evidence_id, excerpt=None)]),
        ([_link(evidence_id, "supports")], [_row(evidence_id)]),
        ([_link(evidence_id, "context")], [_row(evidence_id)]),
        ([_link(evidence_id, "contradicts")], [_row(evidence_id, excerpt=None)]),
        ([_link(evidence_id, "bogus")], [_row(evidence_id)]),
    ]
    allowed = {
        ClaimStatus.SUPPORTED,
        ClaimStatus.PARTIALLY_SUPPORTED,
        ClaimStatus.CONTRADICTED,
        ClaimStatus.INSUFFICIENT_EVIDENCE,
    }
    for links, rows in configs:
        verdict = decide_verdict(links, rows)
        assert verdict in allowed
        assert verdict != ClaimStatus.UNVERIFIED_LEAD


def test_evidence_evolution_models_status_transitions() -> None:
    supporting, contradicting = uuid4(), uuid4()
    support_link = _link(supporting, "supports")
    contra_link = _link(contradicting, "contradicts")
    support_row = _row(supporting)
    contra_row = _row(contradicting, excerpt=None)
    assert decide_verdict([], []) == ClaimStatus.INSUFFICIENT_EVIDENCE
    assert decide_verdict([support_link], [support_row]) == ClaimStatus.SUPPORTED
    assert decide_verdict([support_link, contra_link], [support_row, contra_row]) == (
        ClaimStatus.CONTRADICTED
    )
    assert decide_verdict([], []) == ClaimStatus.INSUFFICIENT_EVIDENCE


def test_missing_information_need_none_when_usable_evidence() -> None:
    claim = {"predicate": "company.registered_name", "subject_entity_id": uuid4()}
    assert missing_information_need(claim, 1) is None
    assert missing_information_need(claim, 3) is None


def test_missing_information_need_typed_dict_without_evidence() -> None:
    subject = uuid4()
    claim = {"predicate": "company.registered_name", "subject_entity_id": subject}
    need = missing_information_need(claim, 0)
    assert need == {
        "predicate": "company.registered_name",
        "information_need": f"Independent evidence for company.registered_name on {subject}",
        "reason": "verifier found no usable evidence",
    }


def test_missing_information_need_without_subject() -> None:
    claim = {"predicate": "company.registered_name", "subject_entity_id": None}
    need = missing_information_need(claim, 0)
    assert need is not None
    assert need["predicate"] == "company.registered_name"
    assert "company.registered_name" in need["information_need"]


def test_verification_result_accepts_all_four_verdicts() -> None:
    for status in (
        ClaimStatus.SUPPORTED,
        ClaimStatus.PARTIALLY_SUPPORTED,
        ClaimStatus.CONTRADICTED,
        ClaimStatus.INSUFFICIENT_EVIDENCE,
    ):
        result = VerificationResult(
            status=status,
            rationale="deterministic verdict",
            supporting_evidence_ids=[],
            contradicting_evidence_ids=[],
        )
        assert result.status == status


def test_schema_invalid_output_fails_closed() -> None:
    with pytest.raises(ValidationError):
        VerificationResult(
            status="MAYBE_SUPPORTED",  # type: ignore[arg-type]
            rationale="invented outcome",
            supporting_evidence_ids=[],
            contradicting_evidence_ids=[],
        )


def test_result_references_only_supplied_evidence_ids() -> None:
    supplied = uuid4()
    result = VerificationResult(
        status=ClaimStatus.SUPPORTED,
        rationale="verdict SUPPORTED: 1 supporting evidence row(s)",
        supporting_evidence_ids=[supplied],
        contradicting_evidence_ids=[],
    )
    assert result.supporting_evidence_ids == [supplied]
    assert "excerpt text" not in result.rationale


def _claim(claim_id, subject, predicate, value, status):
    return {
        "id": claim_id,
        "subject_entity_id": subject,
        "predicate": predicate,
        "value": value,
        "status": status,
    }


def test_contradiction_pair_requires_supported_side() -> None:
    subject = uuid4()
    first, second = uuid4(), uuid4()
    claims = [
        _claim(first, subject, "company.ceo", {"name": "A"}, "SUPPORTED"),
        _claim(second, subject, "company.ceo", {"name": "B"}, "UNVERIFIED_LEAD"),
    ]
    pairs = find_contradiction_pairs(claims)
    assert len(pairs) == 1
    pair = pairs[0]
    assert {pair["claim_a_id"], pair["claim_b_id"]} == {first, second}
    assert pair["predicate"] == "company.ceo"
    assert pair["subject_entity_id"] == subject


def test_contradiction_pair_ignores_equal_values() -> None:
    subject = uuid4()
    claims = [
        _claim(uuid4(), subject, "company.ceo", {"name": "A"}, "SUPPORTED"),
        _claim(uuid4(), subject, "company.ceo", {"name": "A"}, "SUPPORTED"),
    ]
    assert find_contradiction_pairs(claims) == []


def test_contradiction_pair_ignores_null_subjects() -> None:
    claims = [
        _claim(uuid4(), None, "company.ceo", {"name": "A"}, "SUPPORTED"),
        _claim(uuid4(), None, "company.ceo", {"name": "B"}, "SUPPORTED"),
    ]
    assert find_contradiction_pairs(claims) == []


def test_contradiction_pair_ignores_two_weak_claims() -> None:
    subject = uuid4()
    claims = [
        _claim(uuid4(), subject, "company.ceo", {"name": "A"}, "UNVERIFIED_LEAD"),
        _claim(uuid4(), subject, "company.ceo", {"name": "B"}, "INSUFFICIENT_EVIDENCE"),
    ]
    assert find_contradiction_pairs(claims) == []


def test_contradiction_pairs_are_sorted_deterministically() -> None:
    subject = uuid4()
    ids = [UUID(int=index) for index in (30, 10, 20)]
    claims = [
        _claim(claim_id, subject, "company.ceo", {"name": f"Name {index}"}, "SUPPORTED")
        for index, claim_id in enumerate(ids)
    ]
    pairs = find_contradiction_pairs(claims)
    assert len(pairs) == 3
    keys = [
        (str(pair["claim_a_id"]), str(pair["claim_b_id"])) for pair in pairs
    ]
    assert keys == sorted(keys)
    for pair in pairs:
        assert str(pair["claim_a_id"]) <= str(pair["claim_b_id"])
