"""Unit tests for subject-scoped claim fingerprints (AQ-030)."""

import uuid

from apps.api.app.repositories.claims_evidence import claim_fingerprint


def test_subject_scopes_fingerprint() -> None:
    iid = uuid.uuid4()
    first = uuid.uuid4()
    second = uuid.uuid4()
    assert claim_fingerprint(iid, first, "p", {"v": 1}) != claim_fingerprint(
        iid, second, "p", {"v": 1}
    )


def test_missing_subject_is_stable() -> None:
    iid = uuid.uuid4()
    assert claim_fingerprint(iid, None, "p", {"v": 1}) == claim_fingerprint(
        iid, None, "p", {"v": 1}
    )
    assert claim_fingerprint(iid, None, "p", {"v": 1}) != claim_fingerprint(
        iid, uuid.uuid4(), "p", {"v": 1}
    )


def test_predicate_and_value_still_matter() -> None:
    iid = uuid.uuid4()
    subject = uuid.uuid4()
    assert claim_fingerprint(iid, subject, "p1", {"v": 1}) != claim_fingerprint(
        iid, subject, "p2", {"v": 1}
    )
    assert claim_fingerprint(iid, subject, "p", {"v": 1}) != claim_fingerprint(
        iid, subject, "p", {"v": 2}
    )
