import pytest

from apps.api.app.domain.identifiers import (
    InvalidOrganizationNumber,
    is_valid_orgnr,
    normalize_orgnr,
)


def test_valid_organization_number() -> None:
    assert is_valid_orgnr("974760673")
    assert normalize_orgnr("974 760 673") == "974760673"


def test_invalid_check_digit_is_rejected() -> None:
    assert not is_valid_orgnr("974760674")
    with pytest.raises(InvalidOrganizationNumber):
        normalize_orgnr("974760674")


def test_non_numeric_organization_number_is_rejected() -> None:
    with pytest.raises(InvalidOrganizationNumber):
        normalize_orgnr("97476067X")
