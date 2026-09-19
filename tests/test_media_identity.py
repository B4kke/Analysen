from datetime import date

import pytest

from apps.api.app.domain.models import ResolutionState, TargetInput, TargetType
from apps.api.app.services.media_identity import resolve_media_identity


def test_person_name_only_stays_unresolved() -> None:
    target = TargetInput(type=TargetType.PERSON, name="Ola Nordmann")
    result = resolve_media_identity(
        target,
        target_query="Ola Nordmann",
        text_excerpt="Ola Nordmann deltok på møtet.",
    )
    assert result.state == ResolutionState.UNRESOLVED
    assert result.score <= 0.64


def test_person_exact_birth_date_and_place_can_match() -> None:
    target = TargetInput(
        type=TargetType.PERSON,
        name="Ola Nordmann",
        birth_date=date(1980, 4, 3),
        place="Nannestad",
    )
    result = resolve_media_identity(
        target,
        target_query="Ola Nordmann",
        text_excerpt="Ola Nordmann, født 03.04.1980, fra Nannestad, ble omtalt i saken.",
    )
    assert result.state == ResolutionState.MATCH
    assert "exact_birth_date" in result.reasons
    assert "same_place" in result.reasons


def test_person_birth_date_without_second_signal_is_probable() -> None:
    target = TargetInput(
        type=TargetType.PERSON,
        name="Ola Nordmann",
        birth_date=date(1980, 4, 3),
    )
    result = resolve_media_identity(
        target,
        target_query="Ola Nordmann",
        text_excerpt="Ola Nordmann, født 1980-04-03, er omtalt.",
    )
    assert result.state == ResolutionState.PROBABLE_MATCH


def test_company_requires_known_orgnr_for_automatic_match() -> None:
    target = TargetInput(
        type=TargetType.COMPANY,
        name="Eksempel AS",
        known_orgnrs=["974760673"],
    )
    weak = resolve_media_identity(
        target,
        target_query="Eksempel AS",
        text_excerpt="Eksempel AS åpnet nytt kontor.",
    )
    assert weak.state == ResolutionState.UNRESOLVED

    strong = resolve_media_identity(
        target,
        target_query="Eksempel AS",
        text_excerpt="Eksempel AS (org.nr. 974 760 673) åpnet nytt kontor.",
    )
    assert strong.state == ResolutionState.MATCH


@pytest.mark.parametrize("query", ["Annen Person", ""])
def test_untrusted_query_without_target_name_stays_unresolved(query: str) -> None:
    target = TargetInput(type=TargetType.PERSON, name="Ola Nordmann")
    result = resolve_media_identity(
        target,
        target_query=query,
        text_excerpt="Ingen identifiserende opplysninger her.",
    )
    assert result.state == ResolutionState.UNRESOLVED


def test_company_orgnr_does_not_match_concatenated_unrelated_numbers() -> None:
    target = TargetInput(
        type=TargetType.COMPANY,
        name="Eksempel AS",
        known_orgnrs=["974760673"],
    )
    result = resolve_media_identity(
        target,
        target_query="Eksempel AS",
        text_excerpt="Eksempel AS hadde 974 ansatte, 760 saker og 673 kunder.",
    )
    assert result.state == ResolutionState.UNRESOLVED
