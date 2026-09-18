import html
import re
from typing import Any
from urllib.parse import quote

import httpx

from apps.api.app.domain.national_library import (
    NationalLibraryAccess,
    NationalLibraryContentFragment,
    NationalLibraryItem,
)
from apps.api.app.sources.base import DiscoveryAdapter, DiscoveryResult, SourceAdapter, SourceRecord

_EM_RE = re.compile(r"</?em>", re.IGNORECASE)


class NationalLibraryRestrictedContentError(PermissionError):
    """Raised when OCR/image content is not eligible for local capture."""


class NationalLibraryAdapter(SourceAdapter, DiscoveryAdapter):
    """Adapter for Nasjonalbiblioteket's public Catalog Search API.

    Catalog metadata/search remains available for discovery. OCR fragments are
    captured only for digitized public-domain items that are not marked with a
    legal-deposit or geographic/library restriction.
    """

    source_id = "national_library_no"
    provider_id = source_id
    base_url = "https://api.nb.no/catalog/v1"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.client = client or httpx.AsyncClient(timeout=30.0, follow_redirects=False)

    async def search(self, query: str, **kwargs: Any) -> list[DiscoveryResult]:
        items = await self.search_items(query, **kwargs)
        return [
            DiscoveryResult(
                provider=self.provider_id,
                url=item.source_url,
                title=item.title,
                snippet=None,
                rank=index + 1,
            )
            for index, item in enumerate(items)
        ]

    async def search_items(
        self,
        query: str,
        *,
        size: int = 20,
        page: int = 0,
        media_type: str | None = None,
        digital_only: bool = False,
        search_type: str = "FULL_TEXT_SEARCH",
        filters: list[str] | None = None,
    ) -> list[NationalLibraryItem]:
        params: list[tuple[str, str]] = [
            ("q", query),
            ("size", str(max(1, min(size, 50)))),
            ("page", str(max(0, page))),
        ]
        if search_type:
            params.append(("searchType", search_type))

        active_filters = list(filters or [])
        if media_type:
            active_filters.append(f"mediatype:{media_type}")
        if digital_only:
            active_filters.append("digital:Ja")
        params.extend(("filter", value) for value in active_filters)

        response = await self.client.get(f"{self.base_url}/items", params=params)
        response.raise_for_status()
        payload = response.json()
        raw_items = payload.get("_embedded", {}).get("items", [])
        if not isinstance(raw_items, list):
            return []
        return [self._parse_item(item) for item in raw_items if isinstance(item, dict)]

    async def fetch(self, identifier: str) -> SourceRecord:
        response = await self.client.get(self._item_url(identifier))
        response.raise_for_status()
        payload = response.json()
        item = self._parse_item(payload)
        return SourceRecord(
            source_id=self.source_id,
            external_id=item.identifier,
            payload=payload,
            source_url=item.source_url,
        )

    async def get_item(self, identifier: str) -> NationalLibraryItem:
        response = await self.client.get(self._item_url(identifier))
        response.raise_for_status()
        return self._parse_item(response.json())

    async def content_fragments(
        self,
        identifier: str,
        query: str,
        *,
        fragments: int = 10,
        fragment_size: int = 240,
    ) -> list[NationalLibraryContentFragment]:
        item = await self.get_item(identifier)
        if not item.access.allows_content_capture():
            raise NationalLibraryRestrictedContentError(
                f"NB item {item.identifier!r} is searchable as metadata/discovery, "
                "but OCR content capture is blocked by access policy"
            )

        params = {
            "q": query,
            "fragments": max(1, min(fragments, 100)),
            "fragSize": max(20, min(fragment_size, 4000)),
        }
        response = await self.client.get(
            f"{self._item_url(identifier)}/contentfragments",
            params=params,
        )
        response.raise_for_status()
        payload = response.json()
        raw_fragments = payload.get("contentFragments", [])
        if not isinstance(raw_fragments, list):
            return []

        parsed: list[NationalLibraryContentFragment] = []
        for fragment in raw_fragments:
            if not isinstance(fragment, dict):
                continue
            text = fragment.get("text")
            if not isinstance(text, str) or not text.strip():
                continue
            clean_text = html.unescape(_EM_RE.sub("", text)).strip()
            parsed.append(
                NationalLibraryContentFragment(
                    page_id=_string_or_none(fragment.get("pageid")),
                    text=clean_text,
                )
            )
        return parsed

    def _item_url(self, identifier: str) -> str:
        encoded = quote(identifier, safe="")
        return f"{self.base_url}/items/{encoded}"

    def _parse_item(self, payload: dict[str, Any]) -> NationalLibraryItem:
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}

        access_info = payload.get("accessInfo")
        if not isinstance(access_info, dict):
            access_info = {}

        urn = _extract_urn(metadata)
        identifier = (
            _string_or_none(payload.get("id"))
            or urn
            or _string_or_none(metadata.get("id"))
            or _identifier_from_self_link(payload)
        )
        if not identifier:
            raise ValueError("NB item is missing a stable identifier")

        source_url = _self_link(payload) or self._item_url(identifier)

        return NationalLibraryItem(
            identifier=identifier,
            urn=urn,
            title=_first_string(metadata.get("title"))
            or _title_from_infos(metadata.get("titleInfos")),
            creators=_creator_names(metadata.get("creators")),
            media_types=_string_list(metadata.get("mediaTypes")),
            access=NationalLibraryAccess(
                access_allowed_from=_string_or_none(access_info.get("accessAllowedFrom")),
                is_digital=_bool_or_none(access_info.get("isDigital")),
                is_public_domain=_bool_or_none(access_info.get("isPublicDomain")),
                legal_deposit_login_text=_string_or_none(
                    access_info.get("legalDepositLoginText")
                ),
                license=_string_or_none(access_info.get("license")),
                viewability=_string_or_none(access_info.get("viewability")),
            ),
            source_url=source_url,
            raw_metadata=metadata,
        )


def _extract_urn(metadata: dict[str, Any]) -> str | None:
    identifiers = metadata.get("identifiers")
    if isinstance(identifiers, dict):
        return _first_string(identifiers.get("urn"))
    return None


def _title_from_infos(value: Any) -> str | None:
    if not isinstance(value, list):
        return None
    for entry in value:
        if isinstance(entry, dict):
            title = _first_string(entry.get("title"))
            if title:
                return title
    return None


def _creator_names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return _string_list(value)

    names: list[str] = []
    for entry in value:
        if isinstance(entry, str) and entry.strip():
            names.append(entry.strip())
        elif isinstance(entry, dict):
            name = (
                _first_string(entry.get("name"))
                or _first_string(entry.get("creator"))
                or _first_string(entry.get("displayName"))
            )
            if name:
                names.append(name)
    return names


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [
            item.strip()
            for item in value
            if isinstance(item, str) and item.strip()
        ]
    return []


def _first_string(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
    return None


def _string_or_none(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _bool_or_none(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _self_link(payload: dict[str, Any]) -> str | None:
    links = payload.get("_links")
    if not isinstance(links, dict):
        return None
    self_link = links.get("self")
    if isinstance(self_link, dict):
        return _string_or_none(self_link.get("href"))
    return None


def _identifier_from_self_link(payload: dict[str, Any]) -> str | None:
    link = _self_link(payload)
    if not link:
        return None
    return link.rstrip("/").rsplit("/", 1)[-1] or None
