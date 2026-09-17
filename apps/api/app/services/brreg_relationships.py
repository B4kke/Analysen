from datetime import date
from typing import Any

from apps.api.app.domain.brreg_relationships import (
    BrregGroupNode,
    BrregGroupRelationship,
    BrregGroupStructure,
    BrregLegalRole,
    BrregLegalRoleLookup,
    BrregLegalRoleOrganization,
    BrregOrganizationForm,
)
from apps.api.app.domain.identifiers import InvalidOrganizationNumber, normalize_orgnr


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _safe_orgnr(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return normalize_orgnr(str(value))
    except InvalidOrganizationNumber:
        return None


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    if isinstance(value, list):
        cleaned = " ".join(str(part).strip() for part in value if str(part).strip())
        return cleaned or None
    return None


def _organization_form(value: Any) -> BrregOrganizationForm | None:
    if not isinstance(value, dict):
        return None
    code = _text(value.get("kode"))
    description = _text(value.get("beskrivelse"))
    if not code and not description:
        return None
    return BrregOrganizationForm(code=code, description=description)


def normalize_brreg_legal_roles(
    orgnr: str,
    payload: dict[str, Any],
    *,
    page_size: int | None = None,
) -> BrregLegalRoleLookup:
    subject_orgnr = normalize_orgnr(orgnr)
    organizations: list[BrregLegalRoleOrganization] = []

    for entity in payload.get("enheter") or []:
        if not isinstance(entity, dict):
            continue
        target_orgnr = _safe_orgnr(entity.get("organisasjonsnummer"))
        if target_orgnr is None:
            continue

        roles: list[BrregLegalRole] = []
        for role in entity.get("roller") or []:
            if not isinstance(role, dict):
                continue
            role_type = role.get("type") or {}
            if not isinstance(role_type, dict):
                continue
            role_code = _text(role_type.get("kode"))
            if role_code is None:
                continue
            roles.append(
                BrregLegalRole(
                    role_code=role_code,
                    role_description=_text(role_type.get("beskrivelse")),
                    deregistered=bool(role.get("avregistrert")),
                    sequence=(
                        role.get("rekkefolge")
                        if isinstance(role.get("rekkefolge"), int)
                        else None
                    ),
                )
            )

        organizations.append(
            BrregLegalRoleOrganization(
                organization_number=target_orgnr,
                name=_text(entity.get("navn")),
                roles=roles,
            )
        )

    next_search_after = None
    if page_size and len(organizations) >= page_size and organizations:
        next_search_after = organizations[-1].organization_number

    return BrregLegalRoleLookup(
        subject_organization_number=subject_orgnr,
        deleted=bool(payload.get("erSlettet")),
        organizations=organizations,
        next_search_after=next_search_after,
    )


def _normalize_group_node(value: Any) -> BrregGroupNode | None:
    if not isinstance(value, dict):
        return None
    orgnr = _safe_orgnr(value.get("organisasjonsnummer"))
    if orgnr is None:
        return None

    relation_raw = value.get("knytningsform")
    relationship = None
    if isinstance(relation_raw, dict):
        relationship = BrregGroupRelationship(
            code=_text(relation_raw.get("kode")),
            description=_text(relation_raw.get("beskrivelse")),
        )

    children = [
        child
        for raw_child in value.get("children") or []
        if (child := _normalize_group_node(raw_child)) is not None
    ]

    return BrregGroupNode(
        level=value.get("nivaa") if isinstance(value.get("nivaa"), int) else None,
        relationship=relationship,
        name=_text(value.get("navn")),
        organization_number=orgnr,
        parent_name=_text(value.get("parentNavn")),
        parent_organization_number=_safe_orgnr(value.get("parentOrganisasjonsnummer")),
        basis=_text(value.get("grunnlag")),
        relationship_date=_parse_date(value.get("dato")),
        organization_form=_organization_form(value.get("organisasjonsform")),
        children=children,
    )


def normalize_brreg_group_structure(orgnr: str, payload: dict[str, Any]) -> BrregGroupStructure:
    subject_orgnr = normalize_orgnr(orgnr)
    children = [
        child
        for raw_child in payload.get("children") or []
        if (child := _normalize_group_node(raw_child)) is not None
    ]
    return BrregGroupStructure(
        organization_number=subject_orgnr,
        name=_text(payload.get("navn")),
        organization_form=_organization_form(payload.get("organisasjonsform")),
        children=children,
    )
