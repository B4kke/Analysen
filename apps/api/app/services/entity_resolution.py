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
    known_orgnrs: frozenset[str] = frozenset()
    place: str | None = None


@dataclass(frozen=True)
class ResolutionResult:
    state: ResolutionState
    score: float
    reasons: tuple[str, ...]


def resolve_person(target: PersonCandidate, candidate: PersonCandidate) -> ResolutionResult:
    reasons: list[str] = []
    if target.birth_date and candidate.birth_date and target.birth_date != candidate.birth_date:
        return ResolutionResult(ResolutionState.NOT_MATCH, 0.0, ("conflicting_birth_date",))

    name_score = ratio(normalize_name(target.name), normalize_name(candidate.name)) / 100
    score = name_score * 0.30
    reasons.append(f"name_similarity={name_score:.2f}")

    if target.birth_date and candidate.birth_date and target.birth_date == candidate.birth_date:
        score += 0.50
        reasons.append("exact_birth_date")

    shared_orgs = target.known_orgnrs & candidate.known_orgnrs
    if shared_orgs:
        score += min(0.15, 0.05 * len(shared_orgs))
        reasons.append(f"shared_orgs={len(shared_orgs)}")

    if target.place and candidate.place and normalize_name(target.place) == normalize_name(candidate.place):
        score += 0.05
        reasons.append("same_place")

    score = min(score, 1.0)
    if score >= 0.85 and (target.birth_date or shared_orgs):
        state = ResolutionState.MATCH
    elif score >= 0.65 and (target.birth_date or shared_orgs):
        state = ResolutionState.PROBABLE_MATCH
    else:
        state = ResolutionState.UNRESOLVED
    return ResolutionResult(state, score, tuple(reasons))
