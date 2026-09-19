from datetime import date

from apps.api.app.domain.models import ResolutionState
from apps.api.app.services.entity_resolution import (
    PersonCandidate,
    negative_signals,
    resolve_person,
)


def test_conflicting_birth_date_is_not_match() -> None:
    target = PersonCandidate("Ola Nordmann", date(1980, 1, 1))
    candidate = PersonCandidate("Ola Nordmann", date(1981, 1, 1))
    result = resolve_person(target, candidate)
    assert result.state is ResolutionState.NOT_MATCH


def test_name_alone_does_not_auto_match() -> None:
    result = resolve_person(PersonCandidate("Ola Nordmann"), PersonCandidate("Ola Nordmann"))
    assert result.state is ResolutionState.UNRESOLVED


def test_conflicting_birth_year_is_not_match() -> None:
    target = PersonCandidate("Ola Nordmann", birth_year=1980)
    candidate = PersonCandidate("Ola Nordmann", birth_year=1981)
    result = resolve_person(target, candidate)
    assert result.state is ResolutionState.NOT_MATCH
    assert "conflicting_birth_year" in result.reasons


def test_birth_year_against_full_date_conflicts() -> None:
    target = PersonCandidate("Ola Nordmann", birth_year=1980)
    candidate = PersonCandidate("Ola Nordmann", date(1990, 5, 5))
    result = resolve_person(target, candidate)
    assert result.state is ResolutionState.NOT_MATCH
    assert "conflicting_birth_year" in result.reasons


def test_consistent_birth_year_adds_medium_signal() -> None:
    target = PersonCandidate("Ola Nordmann", birth_year=1980)
    candidate = PersonCandidate("Ola Nordmann", birth_year=1980)
    result = resolve_person(target, candidate)
    assert "consistent_birth_year" in result.reasons
    # A bare year is a medium signal: never enough for MATCH on its own.
    assert result.state is ResolutionState.UNRESOLVED


def test_place_mismatch_penalizes_and_reports_signal() -> None:
    target = PersonCandidate("Ola Nordmann", birth_date=date(1980, 1, 1), place="Oslo")
    candidate = PersonCandidate("Ola Nordmann", birth_date=date(1980, 1, 1), place="Bergen")
    plain = resolve_person(
        PersonCandidate("Ola Nordmann", birth_date=date(1980, 1, 1)),
        PersonCandidate("Ola Nordmann", birth_date=date(1980, 1, 1)),
    )
    result = resolve_person(target, candidate)
    assert "place_mismatch" in result.reasons
    assert result.score < plain.score
    assert "place_mismatch" in negative_signals(result)


def test_same_place_still_counts_positive() -> None:
    target = PersonCandidate("Ola Nordmann", place="Oslo")
    candidate = PersonCandidate("Ola Nordmann", place="oslo ")
    result = resolve_person(target, candidate)
    assert "same_place" in result.reasons
    assert "place_mismatch" not in result.reasons


def test_name_only_capped_below_probable_match() -> None:
    # Even a perfect name string with no strong identifier stays UNRESOLVED.
    result = resolve_person(PersonCandidate("Ola Nordmann"), PersonCandidate("Ola Nordmann"))
    assert result.score < 0.65
    assert result.state is ResolutionState.UNRESOLVED
    assert "name_only_insufficient" in negative_signals(result)


def test_exact_birth_date_needs_more_for_match() -> None:
    # Exact birth date with a different first name is only probable:
    # MATCH additionally requires a shared organization or place.
    target = PersonCandidate("Ola Nordmann", date(1980, 1, 1))
    candidate = PersonCandidate("Kari Nordmann", date(1980, 1, 1))
    result = resolve_person(target, candidate)
    assert result.state is ResolutionState.PROBABLE_MATCH
    assert "exact_birth_date" in result.reasons


def test_exact_birth_date_plus_shared_org_matches() -> None:
    target = PersonCandidate(
        "Ola Nordmann", date(1980, 1, 1), known_orgnrs=frozenset({"974760673"})
    )
    candidate = PersonCandidate(
        "Ola Nordmann", date(1980, 1, 1), known_orgnrs=frozenset({"974760673"})
    )
    result = resolve_person(target, candidate)
    assert result.state is ResolutionState.MATCH


def test_negative_signals_extracts_only_negative_codes() -> None:
    target = PersonCandidate("Ola Nordmann", birth_date=date(1980, 1, 1), place="Oslo")
    candidate = PersonCandidate("Ola Nordmann", birth_date=date(1980, 1, 1), place="Bergen")
    result = resolve_person(target, candidate)
    signals = negative_signals(result)
    assert "place_mismatch" in signals
    assert "exact_birth_date" not in signals
    assert "name_similarity=1.00" not in signals
