import gzip
import json
from datetime import date
from pathlib import Path

import pytest

from apps.api.app.services.brreg_role_inventory import (
    UnsupportedRoleInventoryFormat,
    iter_person_role_rows,
)


def _write_gzip_json(path: Path, payload: object) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle)


def test_streams_person_roles_from_inventory(tmp_path: Path) -> None:
    path = tmp_path / "roles.json.gz"
    _write_gzip_json(
        path,
        [
            {
                "organisasjonsnummer": "974760673",
                "rollegrupper": [
                    {
                        "type": {"kode": "STYR", "beskrivelse": "Styre"},
                        "roller": [
                            {
                                "type": {"kode": "LEDE", "beskrivelse": "Styreleder"},
                                "person": {
                                    "navn": {"fornavn": "Ola", "etternavn": "Nordmann"},
                                    "fodselsdato": "1979-01-01",
                                },
                            },
                            {
                                "type": {"kode": "REVI", "beskrivelse": "Revisor"},
                                "enhet": {
                                    "organisasjonsnummer": "923609016",
                                    "navn": ["REVISOR", "AS"],
                                },
                            },
                        ],
                    }
                ],
            }
        ],
    )

    rows = list(iter_person_role_rows(path))

    assert len(rows) == 1
    assert rows[0]["normalized_name"] == "ola nordmann"
    assert rows[0]["birth_date"] == date(1979, 1, 1)
    assert rows[0]["orgnr"] == "974760673"
    assert rows[0]["role_code"] == "LEDE"


def test_rejects_unknown_inventory_shape(tmp_path: Path) -> None:
    path = tmp_path / "roles.json.gz"
    _write_gzip_json(path, [{"unexpected": "shape"}])

    with pytest.raises(UnsupportedRoleInventoryFormat):
        list(iter_person_role_rows(path))


def test_rejects_non_gzip_input(tmp_path: Path) -> None:
    path = tmp_path / "roles.json.gz"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(UnsupportedRoleInventoryFormat):
        list(iter_person_role_rows(path))
