"""Pure NB page/text anchor parsing (AQ-031).

- ``contentfragments`` responses become page locators (item/issue/page URN +
  page number). The fragment ``text`` (typically only
  ``... <em>name</em> ...``) is deliberately discarded: it is a location
  hint, not article text.
- IIIF Content Search responses become ``xywh`` anchors grouped per page.
- DH-lab ``/conc`` responses become bounded keyword-in-context rows marked
  ``PARTIAL_CONTEXT``.

All functions are pure (no network, no LLM), bounded, and deduplicating.
"""

import re
from typing import Any
from urllib.parse import urlsplit

from apps.api.app.domain.nb_media import (
    NBConcreteConcordance,
    NBPageHit,
    NBPageLocator,
    NBTextAnchor,
    NBTextAvailability,
)

MAX_LOCATORS = 50
MAX_ANCHORS_PER_PAGE = 50
MAX_CONCORDANCES = 50

_XYWH_RE = re.compile(r"xywh=(\d+),(\d+),(\d+),(\d+)")
_CANVAS_RE = re.compile(r"/items/(.+)/canvas/(\d+)(?:[/#?]|$)")


def parse_original_url(value: Any) -> str | None:
    """Extract a fetchable original-article URL from upstream NB metadata.

    Only ``http``/``https`` URLs with a hostname qualify: catalog item URLs,
    URNs, relative paths and non-web schemes (``ftp:``, ``javascript:``)
    return None so the web-fetch bridge can never be pointed at a
    non-article target. Pure function: no network.
    """
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        parts = urlsplit(cleaned)
    except Exception:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    return cleaned


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


def _coerce_page_number(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number >= 1 else None


def parse_xywh(value: str | None) -> tuple[int, int, int, int] | None:
    """Parse an ``xywh=x,y,w,h`` fragment; ``None`` when absent/invalid."""
    if not value:
        return None
    match = _XYWH_RE.search(str(value))
    if not match:
        return None
    x, y, w, h = (int(part) for part in match.groups())
    if w < 1 or h < 1 or x < 0 or y < 0:
        return None
    return x, y, w, h


def parse_canvas_reference(value: str | None) -> tuple[str, int] | None:
    """Split an IIIF canvas URL into ``(item_id, canvas page number)``.

    Canvas targets look like
    ``.../items/<item_id>/canvas/<n>#xywh=...`` while contentfragments
    page locators use ``URN:NBN`` page URNs, so the two rarely match
    verbatim. The canvas reference lets the executor correlate them
    without guessing: ``None`` when the value carries no canvas address.
    """
    if not value or not isinstance(value, str):
        return None
    match = _CANVAS_RE.search(value)
    if not match:
        return None
    item_id = match.group(1).strip()
    try:
        page = int(match.group(2))
    except (TypeError, ValueError):
        return None
    if not item_id or page < 1:
        return None
    return item_id, page


def match_page_anchors(
    anchor_pairs: list[tuple[str, str]],
    *,
    item_id: str | None,
    issue_urn: str | None = None,
    page_urn: str | None = None,
    page_number: int | None = None,
) -> list[str]:
    """Select the ``xywh`` anchors belonging to one fragment page.

    Exact ``page_urn`` equality wins. Otherwise an anchor whose canvas URL
    resolves to the same item or issue identifier and canvas number as the
    fragment's ``(item_id/issue_urn, page_number)`` is accepted: live NB
    canvas targets may carry the issue-level identifier rather than the
    item id. Anything else is excluded: anchors from other items, issues
    or pages never leak into a mention. Order is preserved and duplicates
    removed.
    """
    cleaned_item = (item_id or "").strip() or None
    cleaned_issue = (issue_urn or "").strip() or None
    cleaned_urn = (page_urn or "").strip() or None
    matched: list[str] = []
    for anchor_urn, xywh in anchor_pairs:
        anchor_urn_clean = (anchor_urn or "").strip()
        xywh_clean = (xywh or "").strip()
        if not anchor_urn_clean or not xywh_clean:
            continue
        if cleaned_urn is not None and anchor_urn_clean == cleaned_urn:
            if xywh_clean not in matched:
                matched.append(xywh_clean)
            continue
        if not isinstance(page_number, int):
            continue
        canvas = parse_canvas_reference(anchor_urn_clean)
        if canvas is None:
            continue
        canvas_item, canvas_page = canvas
        if (
            canvas_page == page_number
            and canvas_item in {cleaned_item, cleaned_issue} - {None}
            and xywh_clean not in matched
        ):
            matched.append(xywh_clean)
    return matched


def _fragment_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("fragments", "contentFragments", "content_fragments", "results", "items"):
        entries = payload.get(key)
        if isinstance(entries, list):
            return [entry for entry in entries if isinstance(entry, dict)]
    return []


def parse_content_fragments(
    payload: dict[str, Any],
    *,
    item_id: str,
    query: str,
    max_pages: int = MAX_LOCATORS,
) -> list[NBPageLocator]:
    """Map a contentfragments payload to deduplicated page locators.

    Fragment text is intentionally dropped: even large ``fragSize`` values
    may return only ``... <em>query</em> ...`` (live regression 2026-09-18),
    so the output can never be mistaken for article text.
    """
    cleaned_item = (item_id or "").strip()
    if not cleaned_item or not isinstance(payload, dict):
        return []
    bound = max(1, min(int(max_pages), MAX_LOCATORS))
    locators: list[NBPageLocator] = []
    seen: set[str] = set()
    for entry in _fragment_entries(payload):
        if len(locators) >= bound:
            break
        page_urn = _first_present(entry, "pageUrn", "page_urn", "pageId", "urn", "id")
        if page_urn is None:
            continue
        page_urn_str = str(page_urn).strip()
        if not page_urn_str or page_urn_str in seen:
            continue
        seen.add(page_urn_str)
        issue_urn = _first_present(entry, "issueUrn", "issue_urn", "issueId")
        page_number = _coerce_page_number(
            _first_present(entry, "page", "pageNumber", "page_number", "side", "n")
        )
        locators.append(
            NBPageLocator(
                item_id=cleaned_item,
                issue_urn=str(issue_urn).strip() if issue_urn is not None else None,
                page_urn=page_urn_str,
                page_number=page_number,
                query=query or None,
            )
        )
    return locators


def _iiif_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("resources", "hits", "results", "annotations", "items"):
        entries = payload.get(key)
        if isinstance(entries, list):
            return [entry for entry in entries if isinstance(entry, dict)]
    return []


def _canvas_urn(entry: dict[str, Any], target_text: str) -> str | None:
    for key in ("canvas", "pageUrn", "page_urn", "page", "on", "target", "resource"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            candidate = value.strip().split("#")[0].split(" ")[0]
            if candidate:
                return candidate
    if "#" in target_text:
        return target_text.split("#")[0].strip() or None
    return None


def parse_iiif_anchors(
    payload: dict[str, Any],
    *,
    query: str,
    max_anchors: int = MAX_ANCHORS_PER_PAGE * MAX_LOCATORS,
) -> list[NBTextAnchor]:
    """Parse IIIF Content Search hits into deduplicated ``xywh`` anchors."""
    if not isinstance(payload, dict):
        return []
    bound = max(1, min(int(max_anchors), MAX_ANCHORS_PER_PAGE * MAX_LOCATORS))
    anchors: list[NBTextAnchor] = []
    seen: set[tuple[str, str]] = set()
    for entry in _iiif_entries(payload):
        if len(anchors) >= bound:
            break
        target_text = str(
            _first_present(entry, "on", "target", "@id", "id", "canvas") or ""
        )
        coords_source = target_text or str(entry)
        parsed = parse_xywh(coords_source)
        if parsed is None:
            continue
        page_urn = _canvas_urn(entry, target_text)
        if not page_urn:
            continue
        x, y, w, h = parsed
        xywh = f"xywh={x},{y},{w},{h}"
        key = (page_urn, xywh)
        if key in seen:
            continue
        seen.add(key)
        anchors.append(
            NBTextAnchor(
                page_urn=page_urn,
                xywh=xywh,
                x=x,
                y=y,
                w=w,
                h=h,
                target_uri=target_text or None,
                query=query or None,
            )
        )
    return anchors


def parse_iiif_search(
    payload: dict[str, Any],
    *,
    item_id: str,
    query: str,
    issue_urn: str | None = None,
    page_number_by_urn: dict[str, int] | None = None,
) -> list[NBPageHit]:
    """Group IIIF ``xywh`` anchors per page into :class:`NBPageHit` objects."""
    cleaned_item = (item_id or "").strip()
    cleaned_query = (query or "").strip()
    if not cleaned_item or not cleaned_query or not isinstance(payload, dict):
        return []
    anchors = parse_iiif_anchors(payload, query=cleaned_query)
    page_map: dict[str, list[NBTextAnchor]] = {}
    for anchor in anchors:
        page_map.setdefault(anchor.page_urn, []).append(anchor)
    hits: list[NBPageHit] = []
    for page_urn, page_anchors in page_map.items():
        bounded = page_anchors[:MAX_ANCHORS_PER_PAGE]
        page_number = (page_number_by_urn or {}).get(page_urn)
        thumbnail = None
        for entry in _iiif_entries(payload):
            entry_urn = _canvas_urn(
                entry, str(_first_present(entry, "on", "target") or "")
            )
            if entry_urn == page_urn:
                candidate = _first_present(entry, "thumbnail", "thumbnailUrl")
                if isinstance(candidate, str) and candidate.strip():
                    thumbnail = candidate.strip()
                    break
        hits.append(
            NBPageHit(
                item_id=cleaned_item,
                issue_urn=issue_urn,
                page_urn=page_urn,
                page_number=page_number,
                query=cleaned_query,
                anchors=bounded,
                thumbnail_url=thumbnail,
            )
        )
        if len(hits) >= MAX_LOCATORS:
            break
    return hits


def _conc_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("conc", "concordance", "rows", "results", "items"):
        entries = payload.get(key)
        if isinstance(entries, list):
            return [entry for entry in entries if isinstance(entry, dict)]
    return []


def _truncate(text: Any, limit: int = 1000) -> str | None:
    if text is None:
        return None
    cleaned = " ".join(str(text).split())
    if not cleaned:
        return None
    return cleaned[:limit]


def parse_dh_concordance(
    payload: dict[str, Any],
    *,
    max_rows: int = MAX_CONCORDANCES,
) -> list[NBConcreteConcordance]:
    """Parse DH-lab ``/conc`` rows into bounded ``PARTIAL_CONTEXT`` excerpts.

    Never reconstructs full articles: rows are kept separate and truncated.
    """
    if not isinstance(payload, dict):
        return []
    bound = max(1, min(int(max_rows), MAX_CONCORDANCES))
    rows: list[NBConcreteConcordance] = []
    seen: set[tuple[str, str | None, str | None]] = set()
    for entry in _conc_entries(payload):
        if len(rows) >= bound:
            break
        urn = _first_present(entry, "urn", "pageUrn", "id")
        if urn is None:
            continue
        urn_str = str(urn).strip()
        if not urn_str:
            continue
        before = _truncate(_first_present(entry, "before", "left", "prefix", "pre"))
        match = _truncate(_first_present(entry, "word", "match", "query", "keyword"), 500)
        after = _truncate(_first_present(entry, "after", "right", "suffix", "post"))
        key = (urn_str, before, after)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            NBConcreteConcordance(
                urn=urn_str,
                before=before,
                match=match,
                after=after,
                text_availability=NBTextAvailability.PARTIAL_CONTEXT,
            )
        )
    return rows
