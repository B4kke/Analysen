"""Deterministic identity resolution for media mentions.

A newspaper hit is never identity proof by name alone. This module only
promotes a mention when stored context contains corroborating signals already
present on the investigation target. It performs no model calls and never
reaches out to external services.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.domain.models import ResolutionState, TargetInput, TargetType
from apps.api.app.services.entity_resolution import normalize_name


@dataclass(frozen=True)
class MediaIdentityResult:
    state: ResolutionState
    score: float
    reasons: tuple[str, ...]


def _search_normalize(value: str) -> str:
    """Normalize punctuation as separators for conservative phrase matching."""
    return " ".join(
        part for part in re.sub(r"[^a-z0-9]+", " ", normalize_name(value)).split() if part
    )


def _contains_normalized(haystack: str, needle: str) -> bool:
    normalized_haystack = f" {_search_normalize(haystack)} "
    normalized_needle = _search_normalize(needle)
    return bool(normalized_needle) and f" {normalized_needle} " in normalized_haystack


def _digits(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def _contains_numeric_identifier(haystack: str, identifier: str) -> bool:
    digits = _digits(identifier)
    if not digits:
        return False
    pattern = r"(?<!\d)" + r"[\s.\-]*".join(re.escape(ch) for ch in digits) + r"(?!\d)"
    return re.search(pattern, haystack) is not None


def _date_variants(value: date) -> tuple[str, ...]:
    return (
        value.isoformat(),
        value.strftime("%d.%m.%Y"),
        value.strftime("%d/%m/%Y"),
        value.strftime("%d-%m-%Y"),
    )


async def load_verified_aliases(
    session: AsyncSession,
    investigation_id: UUID,
) -> list[str]:
    """Return aliases attached to MATCH entities in this investigation.

    Failure is deliberately fail-closed to an empty list: aliases only widen
    which names can count as trusted identity names; they must never make a
    media lookup fail.
    """
    try:
        rows = (
            await session.execute(
                text("""
                    SELECT DISTINCT ea.alias
                    FROM entity_aliases ea
                    JOIN entities e ON e.id = ea.entity_id
                    JOIN investigation_entities ie ON ie.entity_id = e.id
                    WHERE ie.investigation_id = :id
                      AND e.resolution_state = 'MATCH'
                    ORDER BY ea.alias
                """),
                {"id": investigation_id},
            )
        ).mappings().all()
    except Exception:
        return []
    return [
        str(row["alias"]).strip()
        for row in rows
        if isinstance(row.get("alias"), str) and str(row["alias"]).strip()
    ]


def resolve_media_identity(
    target: TargetInput,
    *,
    target_query: str,
    text_excerpt: str | None,
    verified_aliases: tuple[str, ...] = (),
) -> MediaIdentityResult:
    """Resolve one media mention against the investigation target.

    Exact target/verified-alias name is only a weak signal. Person mentions
    need a strong corroborator (exact birth date or known organization
    identifier) before they can reach PROBABLE_MATCH/MATCH. Company and
    organization mentions require the known organization number for automatic
    MATCH. Everything else stays UNRESOLVED for human review.
    """
    query = (target_query or "").strip()
    excerpt = (text_excerpt or "").strip()
    trusted_names = (target.name, *verified_aliases)
    query_is_trusted = any(
        normalize_name(query) == normalize_name(name)
        for name in trusted_names
        if name and query
    )
    name_in_excerpt = any(
        _contains_normalized(excerpt, name)
        for name in trusted_names
        if name and excerpt
    )
    name_signal = query_is_trusted or name_in_excerpt
    if not name_signal:
        return MediaIdentityResult(
            ResolutionState.UNRESOLVED,
            0.0,
            ("untrusted_or_missing_name_signal",),
        )

    reasons: list[str] = ["verified_name_signal"]
    score = 0.30
    combined_raw = f"{query}\n{excerpt}".casefold()
    org_hits = [
        orgnr
        for orgnr in target.known_orgnrs
        if orgnr and _contains_numeric_identifier(combined_raw, orgnr)
    ]
    org_name_hit = any(
        _contains_normalized(excerpt, name)
        for name in target.known_organizations
        if name and excerpt
    )
    place_hit = bool(target.place and excerpt and _contains_normalized(excerpt, target.place))

    if target.type == TargetType.PERSON:
        exact_birth_date = bool(
            target.birth_date
            and any(value.casefold() in combined_raw for value in _date_variants(target.birth_date))
        )
        target_year = target.birth_date.year if target.birth_date else target.birth_year
        year_hit = bool(
            target_year is not None
            and re.search(rf"(?<!\d){target_year}(?!\d)", combined_raw)
        )
        if exact_birth_date:
            score += 0.50
            reasons.append("exact_birth_date")
        elif year_hit:
            score += 0.15
            reasons.append("consistent_birth_year")
        if org_hits or org_name_hit:
            score += 0.15
            reasons.append("known_organization_context")
        if place_hit:
            score += 0.05
            reasons.append("same_place")

        strong = exact_birth_date or bool(org_hits)
        if not strong:
            reasons.append("name_only_or_weak_context_insufficient")
            return MediaIdentityResult(
                ResolutionState.UNRESOLVED,
                min(score, 0.64),
                tuple(reasons),
            )
        score = min(score, 1.0)
        if score >= 0.85:
            state = ResolutionState.MATCH
        elif score >= 0.65:
            state = ResolutionState.PROBABLE_MATCH
        else:
            state = ResolutionState.UNRESOLVED
        return MediaIdentityResult(state, score, tuple(reasons))

    if target.type in (TargetType.COMPANY, TargetType.ORGANIZATION):
        if org_hits:
            reasons.append("known_organization_number")
            score = min(1.0, score + 0.70)
            return MediaIdentityResult(ResolutionState.MATCH, score, tuple(reasons))
        reasons.append("organization_name_only_insufficient")
        return MediaIdentityResult(
            ResolutionState.UNRESOLVED,
            min(score, 0.64),
            tuple(reasons),
        )

    return MediaIdentityResult(
        ResolutionState.UNRESOLVED,
        min(score, 0.64),
        tuple((*reasons, "unsupported_target_type")),
    )
