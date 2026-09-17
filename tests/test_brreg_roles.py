from datetime import date

from apps.api.app.services.brreg_roles import normalize_brreg_roles


def test_normalizes_person_and_entity_roles() -> None:
    payload = {
        "rollegrupper": [
            {
                "type": {"kode": "STYR", "beskrivelse": "Styre"},
                "sistEndret": "2026-01-12",
                "roller": [
                    {
                        "type": {"kode": "LEDE", "beskrivelse": "Styreleder"},
                        "person": {
                            "navn": {
                                "fornavn": "Ola",
                                "mellomnavn": "Test",
                                "etternavn": "Nordmann",
                            },
                            "fodselsdato": "1979-01-01",
                            "erDoed": False,
                        },
                        "avregistrert": False,
                        "rekkefolge": 1,
                    },
                    {
                        "type": {"kode": "REVI", "beskrivelse": "Revisor"},
                        "enhet": {
                            "organisasjonsnummer": "923609016",
                            "navn": ["REVISOR", "AS"],
                            "organisasjonsform": {"kode": "AS"},
                        },
                    },
                ],
            }
        ]
    }

    result = normalize_brreg_roles("974760673", payload)

    assert result.organization_number == "974760673"
    assert len(result.roles) == 2
    assert result.roles[0].person_name == "Ola Test Nordmann"
    assert result.roles[0].birth_date == date(1979, 1, 1)
    assert result.roles[0].role_code == "LEDE"
    assert result.roles[1].holder_orgnr == "923609016"
    assert result.roles[1].holder_org_name == "REVISOR AS"
