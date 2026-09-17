import gzip
import hashlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import ijson

from apps.api.app.domain.identifiers import normalize_orgnr
from apps.api.app.services.brreg_roles import normalize_brreg_roles
from apps.api.app.services.entity_resolution import normalize_name


class UnsupportedRoleInventoryFormat(ValueError):
    """Raised when a BRREG bulk role record does not match a supported shape."""


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _subject_orgnr(item: dict[str, Any]) -> str:
    candidates = [
        item.get("organisasjonsnummer"),
        item.get("orgnr"),
    ]
    entity = item.get("enhet")
    if isinstance(entity, dict):
        candidates.append(entity.get("organisasjonsnummer"))

    for candidate in candidates:
        if candidate:
            try:
                return normalize_orgnr(str(candidate))
            except ValueError:
                continue
    raise UnsupportedRoleInventoryFormat("Bulk role record is missing a valid organization number")


def iter_inventory_objects(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("rb") as raw:
        magic = raw.read(2)
    if magic != b"\x1f\x8b":
        raise UnsupportedRoleInventoryFormat("BRREG role inventory is not a gzip stream")

    with gzip.open(path, "rb") as stream:
        for item in ijson.items(stream, "item"):
            if not isinstance(item, dict):
                message = "Top-level role inventory items must be objects"
                raise UnsupportedRoleInventoryFormat(message)
            yield item


def iter_person_role_rows(path: Path) -> Iterator[dict[str, Any]]:
    seen_any = False
    for item in iter_inventory_objects(path):
        seen_any = True
        orgnr = _subject_orgnr(item)
        if not isinstance(item.get("rollegrupper"), list):
            raise UnsupportedRoleInventoryFormat(
                "Bulk role record does not contain the expected rollegrupper array"
            )
        lookup = normalize_brreg_roles(orgnr, item)
        for role in lookup.roles:
            if not role.person_name:
                continue
            yield {
                "normalized_name": normalize_name(role.person_name),
                "display_name": role.person_name,
                "birth_date": role.birth_date,
                "orgnr": role.subject_orgnr,
                "role_code": role.role_code,
                "role_description": role.role_description,
                "raw_record": role.model_dump(mode="json", exclude_none=True),
            }
    if not seen_any:
        raise UnsupportedRoleInventoryFormat("BRREG role inventory contained no records")
