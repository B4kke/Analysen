from datetime import date

from apps.api.app.domain.models import ResolutionState
from apps.api.app.services.entity_resolution import PersonCandidate, resolve_person


def test_conflicting_birth_date_is_not_match() -> None:
    target = PersonCandidate("Ola Nordmann", date(1980, 1, 1))
    candidate = PersonCandidate("Ola Nordmann", date(1981, 1, 1))
    result = resolve_person(target, candidate)
    assert result.state is ResolutionState.NOT_MATCH


def test_name_alone_does_not_auto_match() -> None:
    result = resolve_person(PersonCandidate("Ola Nordmann"), PersonCandidate("Ola Nordmann"))
    assert result.state is ResolutionState.UNRESOLVED
