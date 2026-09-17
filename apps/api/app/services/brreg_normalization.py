from datetime import date
from typing import Any

from apps.api.app.domain.identifiers import normalize_orgnr
from apps.api.app.domain.models import BrregAddress, BrregHistoricalName, BrregOrganization


def _parse_date(value: Any) -> date | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _address(payload: Any) -> BrregAddress | None:
    if not isinstance(payload, dict):
        return None
    lines = payload.get("adresse") or []
    if isinstance(lines, str):
        lines = [lines]
    return BrregAddress(
        address_lines=[str(line) for line in lines if line],
        postal_code=payload.get("postnummer"),
        postal_place=payload.get("poststed"),
        municipality=payload.get("kommune"),
        municipality_number=payload.get("kommunenummer"),
        country=payload.get("land"),
        country_code=payload.get("landkode"),
    )


def normalize_brreg_organization(payload: dict[str, Any]) -> BrregOrganization:
    organization_number = normalize_orgnr(str(payload.get("organisasjonsnummer", "")))
    organization_form = payload.get("organisasjonsform") or {}
    industry = payload.get("naeringskode1") or {}
    historical_names: list[BrregHistoricalName] = []
    for item in payload.get("historiskeNavn") or []:
        if not isinstance(item, dict) or not item.get("navn"):
            continue
        historical_names.append(
            BrregHistoricalName(
                name=str(item["navn"]),
                valid_from=_parse_date(item.get("fraDato")),
                valid_to=_parse_date(item.get("tilDato")),
            )
        )

    status_flags = {
        "bankruptcy": bool(payload.get("konkurs")),
        "under_liquidation": bool(payload.get("underAvvikling")),
        "under_compulsory_liquidation_or_dissolution": bool(
            payload.get("underTvangsavviklingEllerTvangsopplosning")
        ),
        "under_reconstruction": bool(payload.get("underRekonstruksjonsforhandling")),
        "under_foreign_insolvency": bool(payload.get("underUtenlandskInsolvensbehandling")),
        "registered_in_vat_register": bool(payload.get("registrertIMvaregisteret")),
        "registered_in_business_register": bool(payload.get("registrertIForetaksregisteret")),
        "registered_in_foundation_register": bool(payload.get("registrertIStiftelsesregisteret")),
        "registered_in_voluntary_register": bool(payload.get("registrertIFrivillighetsregisteret")),
        "part_of_group": bool(payload.get("erIKonsern")),
        "deleted": bool(payload.get("erSlettet") or payload.get("slettedato")),
    }

    return BrregOrganization(
        organization_number=organization_number,
        name=str(payload.get("navn") or "").strip(),
        organization_form_code=organization_form.get("kode"),
        organization_form_description=organization_form.get("beskrivelse"),
        registered_at=_parse_date(payload.get("registreringsdatoEnhetsregisteret")),
        foundation_date=_parse_date(payload.get("stiftelsesdato")),
        deleted_at=_parse_date(payload.get("slettedato")),
        business_address=_address(payload.get("forretningsadresse")),
        postal_address=_address(payload.get("postadresse")),
        website=payload.get("hjemmeside"),
        primary_industry_code=industry.get("kode"),
        primary_industry_description=industry.get("beskrivelse"),
        historical_names=historical_names,
        status_flags=status_flags,
    )
