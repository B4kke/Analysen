from datetime import date
from typing import Any

from apps.api.app.domain.identifiers import normalize_orgnr
from apps.api.app.domain.models import BrregRoleLookup, BrregRoleRecord


def _parse_date(value: Any) -> date | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _person_name(person: dict[str, Any]) -> str | None:
    name = person.get("navn") or {}
    if not isinstance(name, dict):
        return None
    parts = [name.get("fornavn"), name.get("mellomnavn"), name.get("etternavn")]
    value = " ".join(str(part).strip() for part in parts if part and str(part).strip())
    return value or None


def _organization_name(entity: dict[str, Any]) -> str | None:
    value = entity.get("navn")
    if isinstance(value, list):
        joined = " ".join(str(part).strip() for part in value if part and str(part).strip())
        return joined or None
    if isinstance(value, str):
        return value.strip() or None
    return None


def normalize_brreg_roles(orgnr: str, payload: dict[str, Any]) -> BrregRoleLookup:
    subject_orgnr = normalize_orgnr(orgnr)
    records: list[BrregRoleRecord] = []

    for group in payload.get("rollegrupper") or []:
        if not isinstance(group, dict):
            continue
        group_type = group.get("type") or {}
        group_code = group_type.get("kode") if isinstance(group_type, dict) else None
        group_description = group_type.get("beskrivelse") if isinstance(group_type, dict) else None
        group_last_changed = _parse_date(group.get("sistEndret"))

        for role in group.get("roller") or []:
            if not isinstance(role, dict):
                continue
            role_type = role.get("type") or {}
            if not isinstance(role_type, dict) or not role_type.get("kode"):
                continue

            person = role.get("person") if isinstance(role.get("person"), dict) else None
            entity = role.get("enhet") if isinstance(role.get("enhet"), dict) else None
            holder_orgnr: str | None = None
            holder_org_form: str | None = None
            if entity and entity.get("organisasjonsnummer"):
                try:
                    holder_orgnr = normalize_orgnr(str(entity["organisasjonsnummer"]))
                except ValueError:
                    holder_orgnr = None
                form = entity.get("organisasjonsform") or {}
                if isinstance(form, dict):
                    holder_org_form = form.get("kode")

            records.append(
                BrregRoleRecord(
                    subject_orgnr=subject_orgnr,
                    group_code=group_code,
                    group_description=group_description,
                    group_last_changed=group_last_changed,
                    role_code=str(role_type["kode"]),
                    role_description=role_type.get("beskrivelse"),
                    person_name=_person_name(person) if person else None,
                    birth_date=_parse_date(person.get("fodselsdato")) if person else None,
                    deceased=person.get("erDoed") if person else None,
                    holder_orgnr=holder_orgnr,
                    holder_org_name=_organization_name(entity) if entity else None,
                    holder_org_form=holder_org_form,
                    deregistered=bool(role.get("avregistrert")),
                    sequence=role.get("rekkefolge"),
                    responsibility_share=role.get("ansvarsandel"),
                )
            )

    return BrregRoleLookup(organization_number=subject_orgnr, roles=records)
