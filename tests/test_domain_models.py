from datetime import date

import pytest
from pydantic import ValidationError

from apps.api.app.domain.models import TargetInput, TargetType


def test_target_normalizes_known_organization_numbers() -> None:
    target = TargetInput(
        type=TargetType.PERSON,
        name="Ola Nordmann",
        birth_year=1980,
        known_orgnrs=["974 760 673"],
    )
    assert target.known_orgnrs == ["974760673"]


def test_non_person_cannot_have_birth_fields() -> None:
    with pytest.raises(ValidationError):
        TargetInput(
            type=TargetType.COMPANY,
            name="Eksempel AS",
            birth_date=date(1980, 1, 1),
        )


def test_birth_year_must_match_birth_date() -> None:
    with pytest.raises(ValidationError):
        TargetInput(
            type=TargetType.PERSON,
            name="Ola Nordmann",
            birth_date=date(1980, 1, 1),
            birth_year=1981,
        )
