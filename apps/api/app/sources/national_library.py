"""Nasjonalbiblioteket typed adapter (AQ-031).

Covers Catalog search/metadata/contentfragments, IIIF Content Search and
DH-lab concordance behind one injectable client. All network boundaries are
injectable (``httpx.AsyncClient``); methods never leak raw transport
exceptions -- failures surface as typed :class:`NBClientError`.

No method bypasses access controls: no credentials are attached anywhere and
``fetch_page_image`` is the only byte retrieval, gated by the caller's
item-level rights gate (``nb_access_policy``) before it may be invoked.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

import httpx

from apps.api.app.domain.nb_media import NBConcreteConcordance, NBSearchCandidate
from apps.api.app.services.crawler_security import validate_public_http_url
from apps.api.app.services.executors.nb_media import (
    NBCatalogResult,
    NBConcordance,
    NBIssueCandidate,
)
from apps.api.app.services.nb_article_locator import (
    parse_content_fragments,
    parse_dh_concordance,
    parse_iiif_anchors,
    parse_original_url,
)

DEFAULT_CATALOG_BASE_URL = "https://api.nb.no/catalog/v1"
DEFAULT_DHLAB_BASE_URL = "https://api.nb.no/dhlab"
# IIIF Image API resolver (docs/NATIONAL_LIBRARY.md "IIIF-resolvering";
# resolver template per NLN IIIF URL format). Base is injectable; the exact
# live image service for an item is a probe concern, never a hardcoded URL.
DEFAULT_IIIF_IMAGE_BASE_URL = "https://www.nb.no/services/image/resolver"
IIIF_IMAGE_URL_SUFFIX = "full/max/0/default.jpg"

DEFAULT_SEARCH_LIMIT = 25
MAX_SEARCH_LIMIT = 100
DEFAULT_OFFSET = 0
DEFAULT_FRAG_SIZE = 200
MAX_FRAG_SIZE = 5000
DEFAULT_MAX_PAGES = 25
MAX_PAGES_PER_ISSUE = 50
DEFAULT_CONC_WINDOW = 20
MAX_CONC_WINDOW = 100
DEFAULT_CONC_LIMIT = 10
MAX_CONC_LIMIT = 50
# Bounded page/image retrieval (docs/SEARCH_CRAWLING.md: stream and size caps
# are checked while reading; redirect hops are bounded and re-validated).
MAX_PAGE_IMAGE_BYTES = 32 * 1024 * 1024
MAX_PAGE_IMAGE_REDIRECTS = 3
_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})


class NBClientError(Exception):
    """Typed NB transport/upstream failure (never a raw httpx exception)."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class NBRawResponse:
    """Immutable raw upstream envelope persisted before normalization."""

    status_code: int
    payload: dict[str, Any]
    url: str = ""


@dataclass(frozen=True)
class NBItemRecord:
    """Raw item metadata envelope (upstream fields preserved verbatim)."""

    item_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    status_code: int = 200


def _parse_issue_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        try:
            return date(int(value), 1, 1)
        except (ValueError, OverflowError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        compact = text.replace("-", "")
        if len(compact) == 8 and compact.isdigit():
            try:
                return date(int(compact[:4]), int(compact[4:6]), int(compact[6:8]))
            except (ValueError, OverflowError):
                return None
        for candidate in (text[:10], text[:7], text[:4]):
            try:
                if len(candidate) == 10:
                    return date.fromisoformat(candidate)
                if len(candidate) == 7:
                    year, month = candidate.split("-")
                    return date(int(year), int(month), 1)
                if len(candidate) == 4 and candidate.isdigit():
                    return date(int(candidate), 1, 1)
            except (ValueError, OverflowError):
                continue
        return None
    return None


def _nested_dict(item: dict[str, Any], key: str) -> dict[str, Any]:
    """Return ``item[key]`` when it is a dict, else an empty dict."""
    value = item.get(key)
    return value if isinstance(value, dict) else {}


def _first_present(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return item[key]
    lowered = {str(key).lower(): value for key, value in item.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value not in (None, ""):
            return value
    return None



def parse_catalog_search_payload(
    payload: dict[str, Any],
    *,
    query: str,
    limit: int,
) -> tuple[int, list[NBSearchCandidate]]:
    """Parse a Catalog search payload into ``(total, candidates)``.

    Defensive across upstream envelope shapes (``items`` / ``docs`` /
    ``results`` / ``_embedded``). Pure function: no network.
    """
    if not isinstance(payload, dict):
        return 0, []
    raw_total = _first_present(
        payload, "total", "totalElements", "totalHits", "numFound", "size", "count"
    )
    try:
        total = int(raw_total) if raw_total is not None else 0
    except (TypeError, ValueError):
        total = 0
    total = max(0, total)

    raw_items: Any = payload.get("items")
    if raw_items is None:
        raw_items = payload.get("docs")
    if raw_items is None:
        raw_items = payload.get("results")
    if raw_items is None:
        embedded = payload.get("_embedded") or {}
        if isinstance(embedded, dict):
            # Live shape (verified 2026-09-19): hits are grouped per
            # media type under ``mediaTypeResults[].result._embedded.items``.
            # Older/sanitized shapes keep top-level ``items``/``docs``.
            media_groups = embedded.get("mediaTypeResults")
            if isinstance(media_groups, list):
                grouped: list[Any] = []
                for group in media_groups:
                    if not isinstance(group, dict):
                        continue
                    result = group.get("result") or {}
                    inner = result.get("_embedded") or {} if isinstance(result, dict) else {}
                    found = inner.get("items") or inner.get("docs") or []
                    if isinstance(found, list):
                        grouped.extend(found)
                raw_items = grouped
            else:
                raw_items = embedded.get("items") or embedded.get("docs") or []
    if not isinstance(raw_items, list):
        raw_items = []

    candidates: list[NBSearchCandidate] = []
    seen: set[str] = set()
    rank = 0
    for entry in raw_items:
        if len(candidates) >= limit:
            break
        if not isinstance(entry, dict):
            continue
        item_id = _first_present(entry, "itemId", "item_id", "id", "urn", "identifier")
        if item_id is None:
            continue
        item_id_str = str(item_id).strip()
        if not item_id_str or item_id_str in seen:
            continue
        seen.add(item_id_str)
        rank += 1
        # Live item shape nests descriptive fields under ``metadata`` and
        # identifiers (verified 2026-09-19); older shapes keep flat keys.
        nested_metadata = _nested_dict(entry, "metadata")
        identifiers = _nested_dict(nested_metadata, "identifiers")
        origin = _nested_dict(nested_metadata, "originInfo")
        urn = _first_present(identifiers, "urn", "URN")
        publication = _first_present(
            entry, "publication", "publisher", "newspaper", "title", "source", "creator"
        )
        if publication is None:
            publication = _first_present(nested_metadata, "title")
        issued_raw = _first_present(
            entry, "issued", "issueDate", "date", "published", "year", "issued_at"
        )
        if issued_raw is None:
            issued_raw = _first_present(origin, "issued", "dateIssued", "date")
        issue_urn = _first_present(entry, "issueUrn", "issue_urn", "issueId", "urn")
        if issue_urn is None and urn is not None:
            issue_urn = urn
        title = _first_present(entry, "title", "heading", "name")
        if title is None:
            title = _first_present(nested_metadata, "title")
        original_url = parse_original_url(
            _first_present(entry, "originalUrl", "original_url", "originalURL", "fulltextUrl")
        )
        access = entry.get("access") if isinstance(entry.get("access"), dict) else {}
        if not access:
            upstream_access = entry.get("accessInfo")
            access = upstream_access if isinstance(upstream_access, dict) else {}
        metadata: dict[str, Any] = {}
        for key in (
            "accessAllowedFrom",
            "viewability",
            "isPublicDomain",
            "license",
            "licenseCode",
            "rights",
            "rightsUri",
            "attribution",
        ):
            value = _first_present(entry, key)
            if value is not None:
                metadata[key] = value
        if access:
            metadata.update(access)
        candidates.append(
            NBSearchCandidate(
                item_id=item_id_str,
                publication=str(publication).strip() if publication is not None else None,
                issued_at=_parse_issue_date(issued_raw),
                issue_urn=str(issue_urn).strip() if issue_urn is not None else None,
                title=str(title).strip() if title is not None else None,
                rank=rank,
                access_metadata=metadata,
                original_url=original_url,
            )
        )
    return total, candidates


class NationalLibraryClient:
    """Typed NB adapter with injectable base URLs and HTTP client.

    Args:
        catalog_base_url: Catalog API base (no hardcoded URLs in methods).
        dhlab_base_url: DH-lab API base.
        client: Injected ``httpx.AsyncClient`` (tests pass ``MockTransport``).
        iiif_image_base_url: IIIF Image API resolver base used by
            :meth:`NBMediaClientAdapter.fetch_page_image`.
    """

    def __init__(
        self,
        catalog_base_url: str = DEFAULT_CATALOG_BASE_URL,
        dhlab_base_url: str = DEFAULT_DHLAB_BASE_URL,
        client: httpx.AsyncClient | None = None,
        iiif_image_base_url: str = DEFAULT_IIIF_IMAGE_BASE_URL,
    ) -> None:
        self.catalog_base_url = catalog_base_url.rstrip("/")
        self.dhlab_base_url = dhlab_base_url.rstrip("/")
        self.iiif_image_base_url = iiif_image_base_url.rstrip("/")
        self._client = client
        self._owns_client = client is None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0, follow_redirects=False)
            self._owns_client = True
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def _bounded(value: int, default: int, minimum: int, maximum: int) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return default
        return max(minimum, min(maximum, number))

    async def _get_json(self, url: str, params: dict[str, Any]) -> NBRawResponse:
        try:
            response = await self._http().get(url, params=params)
        except httpx.HTTPError as exc:
            raise NBClientError(
                "transport_error", f"NB request failed: {type(exc).__name__}"
            ) from exc
        if response.status_code >= 400:
            raise NBClientError(
                "http_error",
                f"NB request failed with status {response.status_code}",
                status_code=response.status_code,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise NBClientError("invalid_json", "NB response was not JSON") from exc
        if not isinstance(payload, dict):
            payload = {"value": payload}
        return NBRawResponse(status_code=response.status_code, payload=payload, url=url)

    async def _post_json(self, url: str, body: dict[str, Any]) -> NBRawResponse:
        try:
            response = await self._http().post(url, json=body)
        except httpx.HTTPError as exc:
            raise NBClientError(
                "transport_error", f"NB request failed: {type(exc).__name__}"
            ) from exc
        if response.status_code >= 400:
            raise NBClientError(
                "http_error",
                f"NB request failed with status {response.status_code}",
                status_code=response.status_code,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise NBClientError("invalid_json", "NB response was not JSON") from exc
        if not isinstance(payload, dict):
            payload = {"value": payload}
        return NBRawResponse(status_code=response.status_code, payload=payload, url=url)

    async def search_newspapers(
        self,
        query: str,
        *,
        limit: int = DEFAULT_SEARCH_LIMIT,
        offset: int = DEFAULT_OFFSET,
        media_type: str = "aviser",
    ) -> tuple[int, list[NBSearchCandidate], NBRawResponse]:
        """Catalog ``FULL_TEXT_SEARCH`` newspaper discovery (bounded).

        Returns ``(total, candidates, raw)`` where ``raw`` is the immutable
        upstream envelope to persist before normalization. ``limit`` is
        capped at :data:`MAX_SEARCH_LIMIT` so stress queries (Eltonåsen:
        thousands of hits) stop via caps. Dedupes on ``item_id``.
        """
        cleaned = (query or "").strip()
        if not cleaned:
            raise NBClientError("invalid_query", "NB newspaper search requires a query")
        bounded_limit = self._bounded(limit, DEFAULT_SEARCH_LIMIT, 1, MAX_SEARCH_LIMIT)
        bounded_offset = self._bounded(offset, DEFAULT_OFFSET, 0, 1_000_000)
        raw = await self._get_json(
            f"{self.catalog_base_url}/search",
            params={
                "q": cleaned,
                "searchType": "FULL_TEXT_SEARCH",
                "mediaType": media_type,
                "limit": bounded_limit,
                "offset": bounded_offset,
            },
        )
        total, candidates = parse_catalog_search_payload(
            raw.payload, query=cleaned, limit=bounded_limit
        )
        return total, candidates, raw

    async def get_item(self, item_id: str) -> NBItemRecord:
        """Fetch Catalog item metadata (access fields preserved verbatim)."""
        cleaned = (item_id or "").strip()
        if not cleaned:
            raise NBClientError("invalid_item_id", "NB item lookup requires an item id")
        raw = await self._get_json(f"{self.catalog_base_url}/items/{cleaned}", params={})
        return NBItemRecord(item_id=cleaned, payload=raw.payload, status_code=raw.status_code)

    async def content_fragments(
        self,
        item_id: str,
        query: str,
        *,
        frag_size: int = DEFAULT_FRAG_SIZE,
        max_pages: int = DEFAULT_MAX_PAGES,
    ) -> NBRawResponse:
        """Fetch content fragments as page locators (never article text)."""
        cleaned_item = (item_id or "").strip()
        cleaned_query = (query or "").strip()
        if not cleaned_item:
            raise NBClientError("invalid_item_id", "contentfragments requires an item id")
        if not cleaned_query:
            raise NBClientError("invalid_query", "contentfragments requires a query")
        bounded_frag = self._bounded(frag_size, DEFAULT_FRAG_SIZE, 1, MAX_FRAG_SIZE)
        bounded_pages = self._bounded(max_pages, DEFAULT_MAX_PAGES, 1, MAX_PAGES_PER_ISSUE)
        return await self._get_json(
            f"{self.catalog_base_url}/items/{cleaned_item}/contentfragments",
            params={
                "query": cleaned_query,
                "fragSize": bounded_frag,
                "maxPages": bounded_pages,
            },
        )

    async def iiif_search(self, item_id: str, query: str) -> NBRawResponse:
        """IIIF Content Search: OCR tokens + ``xywh`` anchors for an item."""
        cleaned_item = (item_id or "").strip()
        cleaned_query = (query or "").strip()
        if not cleaned_item:
            raise NBClientError("invalid_item_id", "IIIF search requires an item id")
        if not cleaned_query:
            raise NBClientError("invalid_query", "IIIF search requires a query")
        return await self._get_json(
            f"{self.catalog_base_url}/contentsearch/{cleaned_item}/search",
            params={"q": cleaned_query},
        )

    async def dh_concordance(
        self,
        urns: list[str],
        query: str,
        *,
        window: int = DEFAULT_CONC_WINDOW,
        limit: int = DEFAULT_CONC_LIMIT,
    ) -> NBRawResponse:
        """DH-lab ``/conc`` keyword-in-context (bounded; PARTIAL_CONTEXT)."""
        cleaned_urns = [str(urn).strip() for urn in urns if str(urn).strip()]
        cleaned_query = (query or "").strip()
        if not cleaned_urns:
            raise NBClientError("invalid_urns", "DH-lab concordance requires urns")
        if not cleaned_query:
            raise NBClientError("invalid_query", "DH-lab concordance requires a query")
        bounded_window = self._bounded(window, DEFAULT_CONC_WINDOW, 1, MAX_CONC_WINDOW)
        bounded_limit = self._bounded(limit, DEFAULT_CONC_LIMIT, 1, MAX_CONC_LIMIT)
        return await self._post_json(
            f"{self.dhlab_base_url}/conc",
            body={
                "urns": cleaned_urns[:MAX_CONC_LIMIT],
                "query": cleaned_query,
                "window": bounded_window,
                "limit": bounded_limit,
            },
        )


# ---------------------------------------------------------------------------
# NBMediaClient bridge (AQ-031 executor protocol).
#
# services.executors.nb_media consumes a narrower network seam:
# ``catalog_search`` / ``content_fragments`` / ``iiif_search`` /
# ``dhlab_conc`` / ``fetch_page_image``. This bridge adds no endpoint logic
# of its own:
# - parsing reuses the pure ``nb_article_locator`` parsers,
# - ``contentfragments`` stay page locators (fragment text is never article
#   text; live regression 2026-09-18: even large ``fragSize`` returns only
#   ``... <em>target</em> ...``),
# - DH-lab concordance stays bounded keyword-in-context (``PARTIAL_CONTEXT``),
# - ``fetch_page_image`` fetches the IIIF image resolver with a bounded
#   response size, per-hop validated redirects and no credentials; the
#   caller's item-level rights gate decides whether the downloader may be
#   invoked at all, and access controls are never bypassed.
# ---------------------------------------------------------------------------


def _conc_context(row: NBConcreteConcordance) -> str | None:
    """Join one concordance row into a bounded keyword-in-context string."""
    parts = [part for part in (row.before, row.match, row.after) if part]
    joined = " ".join(parts).strip()
    return joined or None


class NBMediaClientAdapter:
    """Bridge :class:`NationalLibraryClient` to the executor protocol.

    The executor (``services.executors.nb_media.NBMediaClient``) consumes
    parsed page locators, ``xywh`` anchors, concordance rows and image bytes.
    This adapter is the canonical implementation of that seam: it reuses the
    typed client and pure parsers instead of duplicating endpoint logic, so
    endpoint shapes live in exactly one place.
    """

    def __init__(
        self,
        client: NationalLibraryClient | None = None,
        raw_sink: Callable[[str], Any] | None = None,
    ) -> None:
        self._client = client
        self._raw_sink = raw_sink

    def _wrapped(self) -> NationalLibraryClient:
        if self._client is None:
            self._client = NationalLibraryClient()
        return self._client

    def _sink_raw(self, payload: dict[str, Any]) -> None:
        """Persist the exact upstream envelope before parsing/normalization.

        ``None`` sink (default) keeps the adapter side-effect free for
        diagnostics; the executor passes the canonical raw store so every
        contentsearch/DH-lab response used as evidence is immutable first.
        """
        if self._raw_sink is None:
            return
        self._raw_sink(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _to_issue(self, candidate: NBSearchCandidate) -> NBIssueCandidate:
        """Map a typed candidate onto the executor issue shape.

        ``issued_at`` is an ISO string because the persistence contract
        parses issue dates; upstream access fields are preserved verbatim
        for the item-level rights decision.
        """
        return NBIssueCandidate(
            item_id=candidate.item_id,
            publication=candidate.publication,
            issued_at=(
                candidate.issued_at.isoformat() if candidate.issued_at is not None else None
            ),
            issue_urn=candidate.issue_urn,
            source_url=f"{self._wrapped().catalog_base_url}/items/{candidate.item_id}",
            access=dict(candidate.access_metadata),
            rank=candidate.rank,
            original_url=candidate.original_url,
        )

    async def catalog_search(self, query: str) -> NBCatalogResult:
        """Catalog ``FULL_TEXT_SEARCH`` -> raw snapshot text + issue candidates."""
        _total, candidates, raw = await self._wrapped().search_newspapers(query)
        # Raw upstream envelope sunk verbatim before adapter-level
        # normalization (``parse_catalog_search_payload`` inside
        # ``search_newspapers`` never mutates ``raw.payload``; the sink keeps
        # the exact envelope even if the executor-level store below fails).
        self._sink_raw(raw.payload)
        return NBCatalogResult(
            raw_text=json.dumps(
                raw.payload, ensure_ascii=False, sort_keys=True, default=str
            ),
            issues=[self._to_issue(candidate) for candidate in candidates],
        )

    async def content_fragments(self, item_id: str, query: str) -> list[Any]:
        """contentfragments -> page locators (locator only, never article text)."""
        raw = await self._wrapped().content_fragments(item_id, query)
        self._sink_raw(raw.payload)
        return list(parse_content_fragments(raw.payload, item_id=item_id, query=query))

    async def iiif_search(self, item_id: str, query: str) -> list[Any]:
        """IIIF Content Search -> ``xywh`` anchors on concrete pages."""
        raw = await self._wrapped().iiif_search(item_id, query)
        self._sink_raw(raw.payload)
        return list(parse_iiif_anchors(raw.payload, query=query))

    async def dhlab_conc(
        self,
        urns: list[str],
        query: str,
        *,
        window: int = DEFAULT_CONC_WINDOW,
        limit: int = DEFAULT_CONC_LIMIT,
    ) -> list[Any]:
        """DH-lab ``/conc`` -> bounded keyword-in-context rows (PARTIAL_CONTEXT)."""
        raw = await self._wrapped().dh_concordance(urns, query, window=window, limit=limit)
        self._sink_raw(raw.payload)
        rows = parse_dh_concordance(raw.payload, max_rows=limit)
        return [
            NBConcordance(urn=row.urn, context=_conc_context(row))
            for row in rows
        ]

    async def fetch_page_image(self, page_urn: str) -> bytes:
        """Fetch original page image bytes from the IIIF resolver (bounded).

        The resolver URL is derived from the configurable image base; no
        credentials are attached and no access control is bypassed. Callers
        invoke this only after the item-level rights gate allows page fetch.
        The response is read with an incremental cap of
        :data:`MAX_PAGE_IMAGE_BYTES`; redirects are bounded and re-validated
        per hop; every failure raises a typed :class:`NBClientError`.
        """
        cleaned = (page_urn or "").strip().rstrip("/")
        if not cleaned:
            raise NBClientError("invalid_page_urn", "page image fetch requires a page urn")
        current = (
            f"{self._wrapped().iiif_image_base_url}/"
            f"{quote(cleaned, safe=':')}/{IIIF_IMAGE_URL_SUFFIX}"
        )
        visited: set[str] = set()
        for _hop in range(MAX_PAGE_IMAGE_REDIRECTS + 1):
            if current in visited:
                raise NBClientError(
                    "redirect_loop", "page image fetch detected a redirect loop"
                )
            visited.add(current)
            await validate_public_http_url(current)
            try:
                async with self._wrapped()._http().stream(
                    "GET", current, follow_redirects=False
                ) as response:
                    status = response.status_code
                    if status in _REDIRECT_STATUS_CODES:
                        current = self._redirect_target(current, response)
                        continue
                    if status >= 400:
                        raise NBClientError(
                            "http_error",
                            f"NB image request failed with status {status}",
                            status_code=status,
                        )
                    content_type = (
                        (response.headers.get("content-type") or "")
                        .split(";")[0]
                        .strip()
                        .lower()
                    )
                    if content_type and not content_type.startswith("image/"):
                        raise NBClientError(
                            "unexpected_content_type",
                            f"NB image resolver returned {content_type}",
                            status_code=status,
                        )
                    length = response.headers.get("content-length", "")
                    if length.isdigit() and int(length) > MAX_PAGE_IMAGE_BYTES:
                        raise NBClientError(
                            "image_too_large",
                            "page image exceeds the bounded size limit",
                        )
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_PAGE_IMAGE_BYTES:
                            raise NBClientError(
                                "image_too_large",
                                "page image exceeds the bounded size limit",
                            )
                        chunks.append(chunk)
            except httpx.HTTPError as exc:
                raise NBClientError(
                    "transport_error",
                    f"NB image request failed: {type(exc).__name__}",
                ) from exc
            image = b"".join(chunks)
            if not image:
                raise NBClientError(
                    "empty_image", "page image resolver returned no bytes", status_code=status
                )
            return image
        raise NBClientError(
            "redirect_error", "page image fetch exceeded the redirect bound"
        )

    @staticmethod
    def _redirect_target(current: str, response: httpx.Response) -> str:
        """Resolve one same-host redirect hop; never leaves the resolver host."""
        location = (response.headers.get("location") or "").strip()
        if not location:
            raise NBClientError(
                "redirect_error",
                "page image redirect missing Location",
                status_code=response.status_code,
            )
        next_url = urljoin(current, location)
        if urlsplit(next_url).netloc.casefold() != urlsplit(current).netloc.casefold():
            raise NBClientError(
                "redirect_error",
                "page image redirect left the resolver host",
                status_code=response.status_code,
            )
        return next_url
