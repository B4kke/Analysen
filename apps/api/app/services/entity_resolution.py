from dataclasses import dataclass
from datetime import date

from rapidfuzz.fuzz import ratio
from unidecode import unidecode

from apps.api.app.domain.models import ResolutionState


def normalize_name(value: str) -> str:
    return " ".join(unidecode(value).casefold().split())


@dataclass(frozen=True)
class PersonCandidate:
    name: str
    birth_date: date | None = None
    birth_year: int | None = None
    known_orgnrs: frozenset[str] = frozenset()
    place: str | None = None


@dataclass(frozen=True)
class ResolutionResult:
    state: ResolutionState
    score: float
    reasons: tuple[str, ...]


#: Reason codes that count as negative signals for persistence and review.
NEGATIVE_SIGNALS = frozenset(
    {
        "conflicting_birth_date",
        "conflicting_birth_year",
        "place_mismatch",
        "name_only_insufficient",
    }
)

#: Above this score a name-only comparison may never climb without a strong
#: identifier (exact birth date, matching birth year context excluded — see
#: below — or a shared organization).
_NAME_ONLY_CAP = 0.64

_PLACE_MISMATCH_PENALTY = 0.25


def _candidate_year(candidate: PersonCandidate) -> int | None:
    if candidate.birth_date is not None:
        return candidate.birth_date.year
    return candidate.birth_year


def negative_signals(result: ResolutionResult) -> tuple[str, ...]:
    """Extract the persistable negative signals from a resolution result."""
    return tuple(reason for reason in result.reasons if reason in NEGATIVE_SIGNALS)


def resolve_person(target: PersonCandidate, candidate: PersonCandidate) -> ResolutionResult:
    reasons: list[str] = []
    if target.birth_date and candidate.birth_date and target.birth_date != candidate.birth_date:
        return ResolutionResult(ResolutionState.NOT_MATCH, 0.0, ("conflicting_birth_date",))

    target_year = _candidate_year(target)
    candidate_year = _candidate_year(candidate)
    if (
        target_year is not None
        and candidate_year is not None
        and target_year != candidate_year
        and not (target.birth_date and candidate.birth_date)
    ):
        return ResolutionResult(ResolutionState.NOT_MATCH, 0.0, ("conflicting_birth_year",))

    name_score = ratio(normalize_name(target.name), normalize_name(candidate.name)) / 100
    score = name_score * 0.30
    reasons.append(f"name_similarity={name_score:.2f}")

    if target.birth_date and candidate.birth_date and target.birth_date == candidate.birth_date:
        score += 0.50
        reasons.append("exact_birth_date")
    elif (
        target_year is not None
        and candidate_year is not None
        and target_year == candidate_year
    ):
        score += 0.15
        reasons.append("consistent_birth_year")

    shared_orgs = target.known_orgnrs & candidate.known_orgnrs
    if shared_orgs:
        score += min(0.15, 0.05 * len(shared_orgs))
        reasons.append(f"shared_orgs={len(shared_orgs)}")

    if target.place and candidate.place:
        if normalize_name(target.place) == normalize_name(candidate.place):
            score += 0.05
            reasons.append("same_place")
        else:
            score -= _PLACE_MISMATCH_PENALTY
            reasons.append("place_mismatch")

    score = max(0.0, score)
    has_strong_identifier = bool(target.birth_date or shared_orgs)
    if not has_strong_identifier:
        reasons.append("name_only_insufficient")
        if score > _NAME_ONLY_CAP:
            score = _NAME_ONLY_CAP

    score = min(score, 1.0)
    if score >= 0.85 and (target.birth_date or shared_orgs):
        state = ResolutionState.MATCH
    elif score >= 0.65 and (target.birth_date or shared_orgs):
        state = ResolutionState.PROBABLE_MATCH
    else:
        state = ResolutionState.UNRESOLVED
    return ResolutionResult(state, score, tuple(reasons))
