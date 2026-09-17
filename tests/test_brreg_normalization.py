from datetime import date

from apps.api.app.services.brreg_normalization import normalize_brreg_organization


def test_normalizes_brreg_organization() -> None:
    payload = {
        "organisasjonsnummer": "974760673",
        "navn": "EKSEMPEL AS",
        "organisasjonsform": {"kode": "AS", "beskrivelse": "Aksjeselskap"},
        "registreringsdatoEnhetsregisteret": "1995-02-20",
        "stiftelsesdato": "1994-12-01",
        "forretningsadresse": {
            "adresse": ["Testveien 1"],
            "postnummer": "0150",
            "poststed": "OSLO",
            "kommune": "OSLO",
            "kommunenummer": "0301",
            "land": "Norge",
            "landkode": "NO",
        },
        "naeringskode1": {"kode": "62.010", "beskrivelse": "Programmeringstjenester"},
        "registrertIForetaksregisteret": True,
        "erIKonsern": True,
        "historiskeNavn": [
            {"navn": "GAMMELT NAVN AS", "fraDato": "2001-01-01", "tilDato": "2005-05-01"}
        ],
    }

    organization = normalize_brreg_organization(payload)

    assert organization.organization_number == "974760673"
    assert organization.name == "EKSEMPEL AS"
    assert organization.organization_form_code == "AS"
    assert organization.registered_at == date(1995, 2, 20)
    assert organization.business_address is not None
    assert organization.business_address.postal_code == "0150"
    assert organization.primary_industry_code == "62.010"
    assert organization.status_flags["registered_in_business_register"] is True
    assert organization.status_flags["part_of_group"] is True
    assert organization.historical_names[0].name == "GAMMELT NAVN AS"
