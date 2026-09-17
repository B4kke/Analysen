from datetime import date

from apps.api.app.services.brreg_relationships import (
    normalize_brreg_group_structure,
    normalize_brreg_legal_roles,
)


def test_normalizes_legal_roles_with_pagination_cursor() -> None:
    payload = {
        "organisasjonsnummer": 974760673,
        "erSlettet": False,
        "enheter": [
            {
                "organisasjonsnummer": "923609016",
                "navn": "REVISOR AS",
                "roller": [
                    {
                        "avregistrert": False,
                        "rekkefolge": 0,
                        "type": {"kode": "REVI", "beskrivelse": "Revisor"},
                    }
                ],
            },
            {
                "organisasjonsnummer": "not-an-orgnr",
                "navn": "SKAL HOPPES OVER",
                "roller": [],
            },
        ],
    }

    result = normalize_brreg_legal_roles("974760673", payload, page_size=1)

    assert result.subject_organization_number == "974760673"
    assert result.deleted is False
    assert len(result.organizations) == 1
    assert result.organizations[0].organization_number == "923609016"
    assert result.organizations[0].name == "REVISOR AS"
    assert result.organizations[0].roles[0].role_code == "REVI"
    assert result.next_search_after == "923609016"


def test_normalizes_group_structure_and_skips_unidentifiable_children() -> None:
    payload = {
        "organisasjonsnummer": "974760673",
        "navn": "MOR AS",
        "organisasjonsform": {"kode": "AS", "beskrivelse": "Aksjeselskap"},
        "children": [
            {
                "nivaa": 1,
                "knytningsform": {"kode": "KDAT", "beskrivelse": "Konsern datter"},
                "navn": "DATTER AS",
                "organisasjonsnummer": "923609016",
                "parentNavn": "MOR AS",
                "parentOrganisasjonsnummer": "974760673",
                "grunnlag": "100%",
                "dato": "2026-05-05",
                "organisasjonsform": {"kode": "AS", "beskrivelse": "Aksjeselskap"},
                "children": [],
            },
            {"navn": "UKJENT UTEN IDENTIFIKATOR"},
        ],
    }

    result = normalize_brreg_group_structure("974760673", payload)

    assert result.organization_number == "974760673"
    assert result.organization_form is not None
    assert result.organization_form.code == "AS"
    assert len(result.children) == 1
    child = result.children[0]
    assert child.organization_number == "923609016"
    assert child.parent_organization_number == "974760673"
    assert child.relationship is not None
    assert child.relationship.code == "KDAT"
    assert child.basis == "100%"
    assert child.relationship_date == date(2026, 5, 5)
