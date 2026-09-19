"""NB newspaper executor: admitted ``nb_newspaper_search`` lead -> media mentions.

Thin orchestration wiring (AQ-031), not the adapter/policy/extraction work:

- network goes only through the injected client (the
  ``NBMediaClient`` protocol; the canonical implementation is
  ``apps.api.app.sources.national_library.NBMediaClientAdapter``);
  base URLs live in the client, never in this body,
- the exact Catalog response is stored via the existing raw-store mechanism
  before parsing; the adapter also sinks raw contentfragments / IIIF
  Content Search / DH-lab envelopes before parsing them,
- an item-level access decision is required per issue candidate BEFORE any
  page-image download; restricted content never triggers a download (the
  fetch helper re-checks the verdict immediately before invoking the
  downloader, so a denied verdict raises before any bytes move),
- ``contentfragments`` are page locators only and are never stored as
  article text; DH-lab concordance is lawful context marked
  ``PARTIAL_CONTEXT`` (never ``FULL``),
- permitted pages (explicit ``allow_derived_crop``) go
  page bytes -> raw store -> IIIF-anchored article crop -> Norwegian OCR ->
  validated crop Document/Evidence with parent page URN, exact crop
  geometry and both hashes,
- mentions persist through the canonical ``media_mentions`` repository
  contract (injectable for tests; lazy canonical import in production),
- dedup on (item, page, query), deterministic caps (max 25 issues, max 5
  pages per issue), deterministic stop reasons.

Status, audit and coverage follow the existing executor convention: every
outcome is terminal (COMPLETED/FAILED), failures carry a machine-readable
blocked_reason, and every outcome is audited with a LEAD_EXECUTED event.
Same-name hits start as ``UNRESOLVED`` — name alone is never identity.
A deterministic post-persist identity bridge may promote only when the stored
context corroborates target facts; promoted mentions create evidence-backed
claims that pass through the canonical verifier. No model calls.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.domain.models import ClaimStatus, Lead, ResolutionState
from apps.api.app.domain.scope import QueryClass, ScopeModule, TriggerType
from apps.api.app.repositories import investigations as repository
from apps.api.app.services.nb_article_extract import (
    NBExtractError,
    PageOcrFn,
    extract_permitted_article,
)
from apps.api.app.services.media_identity import load_verified_aliases, resolve_media_identity
from apps.api.app.services.nb_article_locator import match_page_anchors, parse_original_url
from apps.api.app.services.raw_store import store_raw_bytes, store_raw_snapshot

LEAD_TYPE = "nb_newspaper_search"
PROVIDER = "nb_catalog"

# Original-URL bridge (AQ-035): at most this many gated web_document_fetch
# proposals per NB lead. Each proposal passes the deterministic lead gate
# (propose_lead) before it can run; the bridge never fetches anything itself.
MAX_ORIGINAL_URL_BRIDGES = 5

# docs/NATIONAL_LIBRARY.md "Budgets and stop rules": bounded per query.
MAX_ISSUES_PER_QUERY = 25
MAX_PAGES_PER_ISSUE = 5
MAX_DUPLICATE_SKIPS = 25

# DH-lab /conc bounds from docs/NATIONAL_LIBRARY.md ("bounded window/limit").
CONC_WINDOW = 10
CONC_LIMIT = 5

DEFAULT_QUERY_CLASS = QueryClass.ENTITY_ALIAS_EXACT

# Access classes from docs/NATIONAL_LIBRARY.md. Anything outside the two
# PUBLIC_* states counts as restricted for coverage purposes.
RESTRICTED_ACCESS_CLASSES = frozenset({"LIBRARY_ONLY", "NB_ONLY", "UNKNOWN"})


# ---------------------------------------------------------------------------
# Injected NB client surface.
#
# This Protocol documents the seam the canonical NationalLibraryClient must
# satisfy. The executor only uses these methods and only through attribute
# access, so endpoint-level parsing details stay in the adapter. Candidates
# and hits may be mappings or attribute objects; _field() reads either.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NBIssueCandidate:
    """One Catalog issue candidate (discovery, not identity)."""

    item_id: str
    publication: str | None = None
    issued_at: str | None = None
    issue_urn: str | None = None
    source_url: str | None = None
    access: dict[str, Any] = field(default_factory=dict)
    rank: int | None = None
    original_url: str | None = None


@dataclass(frozen=True)
class NBCatalogResult:
    """Catalog FULL_TEXT_SEARCH outcome: immutable raw plus parsed issues."""

    raw_text: str
    issues: list[Any] = field(default_factory=list)


@dataclass(frozen=True)
class NBPageLocator:
    """contentfragments-derived page location (locator only, never text)."""

    item_id: str
    issue_urn: str | None = None
    page_urn: str | None = None
    page_number: int | None = None


@dataclass(frozen=True)
class NBXywhAnchor:
    """IIIF Content Search token anchor on a concrete page."""

    page_urn: str | None = None
    xywh: str | None = None


@dataclass(frozen=True)
class NBConcordance:
    """One bounded DH-lab keyword-in-context row (PARTIAL_CONTEXT)."""

    urn: str | None = None
    context: str | None = None


class NBMediaClient(Protocol):
    """Network seam for the NB chain; implemented by the NB adapter/fakes."""

    async def catalog_search(self, query: str) -> NBCatalogResult: ...
    async def content_fragments(self, item_id: str, query: str) -> list[Any]: ...
    async def iiif_search(self, item_id: str, query: str) -> list[Any]: ...
    async def dhlab_conc(
        self, urns: list[str], query: str, *, window: int = CONC_WINDOW, limit: int = CONC_LIMIT
    ) -> list[Any]: ...
    async def fetch_page_image(self, page_urn: str) -> bytes: ...


# ---------------------------------------------------------------------------
# Access verdict seam.
#
# Canonical item-level policy lives in services.nb_access_policy (parallel
# deliverable). Until it lands — and whenever it is unavailable or errors —
# this module fails closed: metadata + lawful context may be stored, but page
# fetch, full-text storage and report embedding are never allowed.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NBAccessVerdict:
    access_class: str = "UNKNOWN"
    license_code: str | None = None
    allow_metadata: bool = True
    allow_context: bool = True
    allow_full_text_storage: bool = False
    allow_page_fetch: bool = False
    allow_derived_crop: bool = False
    allow_report_embed: bool = False
    reason: str = "conservative default: canonical NB policy unavailable"


class NBPageFetchDenied(Exception):
    """Rights gate refusal: the page-image downloader must not be invoked."""

    def __init__(self, message: str, *, access_class: str = "UNKNOWN") -> None:
        super().__init__(message)
        self.access_class = access_class


async def fetch_permitted_page_image(
    client: NBMediaClient, verdict: NBAccessVerdict, page_urn: str | None
) -> bytes:
    """Fetch page bytes only after the rights gate explicitly allows it.

    A denied verdict (or a missing page URN) raises
    :class:`NBPageFetchDenied` BEFORE the client's downloader is invoked, so
    restricted items can never trigger a page-image call however the caller
    is wired. Transport failures propagate typed from the client.
    """
    if page_urn is None or not str(page_urn).strip():
        raise NBPageFetchDenied("page fetch denied: missing page urn", access_class="UNKNOWN")
    if not verdict.allow_page_fetch:
        raise NBPageFetchDenied(
            f"page fetch denied for access class {verdict.access_class}: {verdict.reason}",
            access_class=verdict.access_class,
        )
    image = await client.fetch_page_image(str(page_urn).strip())
    if not isinstance(image, (bytes, bytearray)) or not bytes(image):
        raise NBPageFetchDenied(
            f"page image resolver returned no bytes for {str(page_urn).strip()}",
            access_class=verdict.access_class,
        )
    return bytes(image)


def _field(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _coerce_published_at(value: Any) -> date | None:
    """Normalize an upstream issue date into a real date (asyncpg is strict).

    The NBMediaClient bridge delivers issue dates as ISO strings per the
    executor issue contract; persistence requires a ``date`` value, so a
    plain string is parsed instead of being dropped or sent raw.
    """
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None
        try:
            return date.fromisoformat(cleaned[:10])
        except ValueError:
            return None
    return None


def conservative_access_verdict(candidate: Any) -> NBAccessVerdict:
    """Fail-closed per-item verdict used without the canonical policy module.

    Upstream access fields are preserved for reporting, but nothing beyond
    metadata + concordance context is ever permitted here. In particular
    ``viewability`` alone never unlocks page fetch or embedding.
    """
    access = _field(candidate, "access", {}) or {}
    if not isinstance(access, dict):
        access = {}
    license_code = access.get("license_code") or access.get("license")
    if access.get("isPublicDomain") is True or access.get("viewability") == "ALL":
        access_class = "PUBLIC_VIEW_ONLY"
    else:
        access_class = "UNKNOWN"
    return NBAccessVerdict(
        access_class=access_class,
        license_code=license_code,
        reason="conservative default: canonical NB policy unavailable",
    )


def _load_canonical_access_decider() -> Any | None:
    """Return the canonical per-item decider, or None when it is unavailable.

    The canonical policy exposes ``decide_item_access(candidate)`` returning
    an ``NBAccessDecision`` (state-based). The executor verdict reads
    verdict-style field names, so the loaded decider is wrapped to map the
    canonical decision through ``_as_policy_dict``.
    """
    try:
        from apps.api.app.services import nb_access_policy as policy
    except ImportError:
        return None
    decider = getattr(policy, "decide_item_access", None)
    if decider is None:
        return None

    def _wrapped(candidate: Any) -> Any:
        decision = decider(candidate)
        mapper = getattr(policy, "_as_policy_dict", None)
        if mapper is not None:
            return mapper(decision)
        return decision

    return _wrapped


def _resolve_access(candidate: Any, *, decider: Any | None = None) -> NBAccessVerdict:
    """Decide per-item access; fail closed on any policy error."""
    if decider is None:
        decider = _load_canonical_access_decider()
    if decider is None:
        return conservative_access_verdict(candidate)
    try:
        raw = decider(candidate)
    except Exception:
        return conservative_access_verdict(candidate)
    try:
        return NBAccessVerdict(
            access_class=str(_field(raw, "access_class", "UNKNOWN") or "UNKNOWN"),
            license_code=_field(raw, "license_code"),
            allow_metadata=bool(_field(raw, "allow_metadata", False)),
            allow_context=bool(_field(raw, "allow_context", False)),
            allow_full_text_storage=bool(_field(raw, "allow_full_text_storage", False)),
            allow_page_fetch=bool(_field(raw, "allow_page_fetch", False)),
            allow_derived_crop=bool(_field(raw, "allow_derived_crop", False)),
            allow_report_embed=bool(_field(raw, "allow_report_embed", False)),
            reason=str(_field(raw, "reason", "canonical NB policy") or "canonical NB policy"),
        )
    except Exception:
        return conservative_access_verdict(candidate)


# ---------------------------------------------------------------------------
# Persistence seam: canonical media_mentions repository contract.
# ---------------------------------------------------------------------------


def _default_persist(session: AsyncSession, **kwargs: Any) -> Any:
    """Persist through the canonical repository; never through a local copy."""
    from apps.api.app.repositories import media_mentions as store

    return store.upsert_media_mention(session, **kwargs)


def _default_client() -> Any | None:
    """Construct the canonical NBMediaClient bridge without hardcoded URLs."""
    try:
        from apps.api.app.sources.national_library import (
            NationalLibraryClient,
            NBMediaClientAdapter,
        )
    except ImportError:
        return None
    return NBMediaClientAdapter(
        NationalLibraryClient(), raw_sink=lambda payload: store_raw_snapshot(payload)
    )


def _query_class(raw: Any) -> QueryClass:
    if isinstance(raw, str):
        try:
            return QueryClass(raw)
        except ValueError:
            return DEFAULT_QUERY_CLASS
    return DEFAULT_QUERY_CLASS


async def _fail(
    session: AsyncSession, investigation_id: UUID, lead_id: UUID, reason: str
) -> str:
    await repository.set_lead_status(session, investigation_id, lead_id, "FAILED", reason)
    await repository._audit(
        session,
        investigation_id,
        "LEAD_EXECUTED",
        {"lead_id": str(lead_id), "status": "FAILED", "reason": reason},
    )
    return "FAILED"


async def execute_nb_media_lead(
    session: AsyncSession,
    investigation_id: UUID,
    lead_id: UUID,
    lead: Lead,
    client: NBMediaClient | None = None,
    persist_fn: Any | None = None,
    access_decider: Any | None = None,
    page_ocr_fn: PageOcrFn | None = None,
    crop_ocr_fn: PageOcrFn | None = None,
) -> str:
    """Execute one admitted PENDING ``nb_newspaper_search`` lead.

    Returns the terminal status (COMPLETED/FAILED). ``client`` is the
    injectable NB chain; ``persist_fn`` defaults to the canonical
    ``media_mentions.upsert_media_mention`` contract; ``access_decider``
    defaults to the canonical item-level policy with a fail-closed fallback.
    ``page_ocr_fn``/``crop_ocr_fn`` inject the Norwegian word-OCR backends for
    the permitted crop path (default ``None`` keeps the production
    pytesseract backend; tests inject fakes so the Document/Evidence linkage
    is provable without the native OCR stack).
    """
    value = lead.value if isinstance(lead.value, dict) else {}
    query = value.get("query")
    if not isinstance(query, str) or len(query.strip()) < 3:
        return await _fail(session, investigation_id, lead_id, "invalid_nb_value")
    query = query.strip()
    query_class = _query_class(value.get("query_class"))

    await repository.set_lead_status(session, investigation_id, lead_id, "RUNNING")

    resolved_client = client if client is not None else _default_client()
    if resolved_client is None:
        return await _fail(session, investigation_id, lead_id, "executor_unavailable")
    # Fail closed on a wrongly wired client (e.g. a raw transport client
    # instead of the adapter bridge): missing capabilities never crash the
    # pass with an AttributeError, they refuse with an explicit reason.
    if not all(
        callable(getattr(resolved_client, name, None))
        for name in (
            "catalog_search",
            "content_fragments",
            "iiif_search",
            "dhlab_conc",
            "fetch_page_image",
        )
    ):
        return await _fail(session, investigation_id, lead_id, "executor_unavailable")
    persist = persist_fn if persist_fn is not None else _default_persist

    try:
        result = await resolved_client.catalog_search(query)
    except Exception as exc:
        return await _fail(
            session, investigation_id, lead_id, f"source_error:{type(exc).__name__}"
        )

    # Immutable raw Catalog snapshot before any parsing/normalization.
    raw_text = _field(result, "raw_text", "")
    if isinstance(raw_text, (dict, list)):
        raw_text = json.dumps(raw_text, ensure_ascii=False, sort_keys=True, default=str)
    if not isinstance(raw_text, str) or not raw_text:
        raw_text = "{}"
    store_raw_snapshot(raw_text)

    all_issues = list(_field(result, "issues", []) or [])
    capped = len(all_issues) > MAX_ISSUES_PER_QUERY
    issues = all_issues[:MAX_ISSUES_PER_QUERY]

    query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()
    await session.execute(
        text("""
            INSERT INTO search_queries (
                investigation_id, provider, query, query_hash,
                originating_lead_id, scope_area, query_class,
                information_need, reason
            ) VALUES (
                :investigation_id, :provider, :query, :query_hash,
                :originating_lead_id, :scope_area, :query_class,
                :information_need, :reason
            )
            ON CONFLICT (investigation_id, provider, query_hash) DO NOTHING
        """),
        {
            "investigation_id": investigation_id,
            "provider": PROVIDER,
            "query": query,
            "query_hash": query_hash,
            "originating_lead_id": lead_id,
            "scope_area": lead.scope_area.value,
            "query_class": query_class.value,
            "information_need": lead.information_need,
            "reason": lead.reason,
        },
    )

    seen: set[tuple[str | None, str | None, str]] = set()
    candidate_count = len(issues)
    located_count = 0
    concordance_count = 0
    mention_count = 0
    fulltext_count = 0
    restricted_count = 0
    page_fetch_count = 0
    page_fetch_blocked = 0
    crop_count = 0
    crop_skipped = 0
    content_fragment_errors = 0
    iiif_errors = 0
    concordance_errors = 0
    identity_match_count = 0
    identity_probable_count = 0
    identity_unresolved_count = 0
    duplicate_skips = 0
    dhlab_attempted = False
    earliest_issued: date | None = None
    latest_issued: date | None = None
    stop_reason = "issue_cap_reached" if capped else "completed"

    for issue in issues:
        item_id = _field(issue, "item_id")
        issue_urn = _field(issue, "issue_urn")
        publication = _field(issue, "publication")
        issued_at = _field(issue, "issued_at")
        source_url = _field(issue, "source_url")
        access = _field(issue, "access", {}) or {}
        upstream_license = access.get("license_code") if isinstance(access, dict) else None

        verdict = _resolve_access(issue, decider=access_decider)
        if verdict.access_class in RESTRICTED_ACCESS_CLASSES:
            restricted_count += 1

        issued = _coerce_published_at(issued_at)
        if issued is not None:
            if earliest_issued is None or issued < earliest_issued:
                earliest_issued = issued
            if latest_issued is None or issued > latest_issued:
                latest_issued = issued

        try:
            fragments = await resolved_client.content_fragments(str(item_id), query)
        except Exception:
            content_fragment_errors += 1
            fragments = []
        pages = [page for page in (fragments or [])][:MAX_PAGES_PER_ISSUE]

        try:
            anchors = await resolved_client.iiif_search(str(item_id), query)
        except Exception:
            iiif_errors += 1
            anchors = []
        # IIIF anchor targets are canvas URLs while fragment locators are
        # URN page identifiers, so verbatim dict lookup would silently drop
        # them. Keep the flat (page_urn, xywh) pairs and correlate per page
        # with match_page_anchors (exact URN first, canvas fallback).
        anchor_pairs: list[tuple[str, str]] = []
        for anchor in anchors or []:
            anchor_page = _field(anchor, "page_urn")
            xywh = _field(anchor, "xywh")
            if (
                isinstance(anchor_page, str)
                and anchor_page.strip()
                and isinstance(xywh, str)
                and xywh.strip()
            ):
                pair = (anchor_page.strip(), xywh.strip())
                if pair not in anchor_pairs:
                    anchor_pairs.append(pair)

        page_urns = [
            str(_field(page, "page_urn"))
            for page in pages
            if _field(page, "page_urn") is not None
        ]
        conc_by_urn: dict[str, str] = {}
        if page_urns and verdict.allow_context:
            dhlab_attempted = True
            try:
                concs = await resolved_client.dhlab_conc(
                    page_urns, query, window=CONC_WINDOW, limit=CONC_LIMIT
                )
            except Exception:
                concordance_errors += 1
                concs = []
            for conc in concs or []:
                urn = _field(conc, "urn")
                context = _field(conc, "context")
                if (
                    isinstance(urn, str)
                    and isinstance(context, str)
                    and context.strip()
                    and urn not in conc_by_urn
                ):
                    conc_by_urn[urn] = context

        if not pages:
            # Treff/side/metadata/link only: document the hit as UNAVAILABLE.
            outcome = await _persist_mention(
                session,
                investigation_id,
                lead_id,
                persist,
                target_query=query,
                publication=publication,
                published_at=issued_at,
                page_number=None,
                issue_urn=issue_urn,
                page_urn=None,
                headline=None,
                summary=None,
                text_excerpt=None,
                text_availability="UNAVAILABLE",
                source_url=source_url,
                verdict=verdict,
                upstream_license=upstream_license,
            )
            if outcome is None:
                return await _fail(
                    session, investigation_id, lead_id, "persist_error:MediaMentionPersistFailed"
                )
            mention_count += 1
            identity_unresolved_count += 1
            continue

        for page in pages:
            page_urn = _field(page, "page_urn")
            page_number = _field(page, "page_number")
            key = (
                str(item_id) if item_id is not None else None,
                str(page_urn) if page_urn is not None else str(page_number),
                query,
            )
            if key in seen:
                duplicate_skips += 1
                if duplicate_skips >= MAX_DUPLICATE_SKIPS:
                    stop_reason = "duplicate_results"
                    break
                continue
            seen.add(key)
            if page_urn is not None:
                located_count += 1

            context = conc_by_urn.get(str(page_urn)) if page_urn is not None else None
            if context is not None:
                concordance_count += 1

            # Correlated IIIF anchors for this fragment page (exact URN,
            # else canvas fallback): used both as the crop extraction anchor
            # and as typed per-mention persistence below.
            page_anchors = match_page_anchors(
                anchor_pairs,
                item_id=str(item_id) if item_id is not None else None,
                issue_urn=issue_urn if isinstance(issue_urn, str) else None,
                page_urn=str(page_urn) if page_urn is not None else None,
                page_number=page_number if isinstance(page_number, int) else None,
            )

            # Policy checked first AND re-checked inside the fetch helper: only
            # an explicit allow reaches the downloader. Raw bytes snapshotted
            # immutably; a validated Norwegian-OCR article crop becomes a
            # derived Document/Evidence with parent geometry (best-effort: a
            # skipped crop never blocks the mention itself).
            image_document_id: UUID | None = None
            crop_text: str | None = None
            crop_evidence_id: UUID | None = None
            image_allowed = verdict.allow_page_fetch and page_urn is not None
            if not image_allowed:
                page_fetch_blocked += 1
            else:
                try:
                    image_bytes = await fetch_permitted_page_image(
                        resolved_client, verdict, str(page_urn)
                    )
                except NBPageFetchDenied:
                    page_fetch_blocked += 1
                    image_bytes = b""
                except Exception as exc:
                    return await _fail(
                        session,
                        investigation_id,
                        lead_id,
                        f"source_error:{type(exc).__name__}",
                    )
                if isinstance(image_bytes, (bytes, bytearray)) and bytes(image_bytes):
                    # PUBLIC_VIEW_ONLY may be fetched for an in-memory, rights-gated
                    # derived crop but the full page is not retained unless the
                    # item policy explicitly allows full-content storage.
                    if verdict.allow_full_text_storage:
                        store_raw_bytes(bytes(image_bytes))
                    page_fetch_count += 1
                    crop_attempted = bool(verdict.allow_derived_crop and page_anchors)
                    image_document_id, crop_text, crop_evidence_id = (
                        await _extract_and_persist_crop(
                            session,
                            investigation_id,
                            item_id=str(item_id) if item_id is not None else None,
                            issue_urn=issue_urn if isinstance(issue_urn, str) else None,
                            page_urn=str(page_urn) if page_urn is not None else None,
                            page_number=page_number if isinstance(page_number, int) else None,
                            publication=publication if isinstance(publication, str) else None,
                            issued_at=issued_at,
                            source_url=source_url if isinstance(source_url, str) else None,
                            query=query,
                            anchors=page_anchors,
                            page_bytes=bytes(image_bytes),
                            verdict=verdict,
                            upstream_license=upstream_license,
                            page_ocr_fn=page_ocr_fn,
                            crop_ocr_fn=crop_ocr_fn,
                        )
                    )
                    if image_document_id is not None:
                        crop_count += 1
                    elif crop_attempted:
                        crop_skipped += 1

            # contentfragments are locators only: the excerpt comes exclusively
            # from lawful context — validated crop OCR first, otherwise DH-lab
            # concordance (PARTIAL_CONTEXT) — and stays absent otherwise. NB
            # crop text is article-region context, never FULL article text.
            excerpt = crop_text if crop_text else context
            availability = "PARTIAL_CONTEXT" if excerpt is not None else "UNAVAILABLE"
            if availability == "FULL":
                fulltext_count += 1
            outcome = await _persist_mention(
                session,
                investigation_id,
                lead_id,
                persist,
                target_query=query,
                publication=publication,
                published_at=issued_at,
                page_number=page_number if isinstance(page_number, int) else None,
                issue_urn=issue_urn,
                page_urn=str(page_urn) if page_urn is not None else None,
                headline=None,
                summary=None,
                text_excerpt=excerpt,
                text_availability=availability,
                source_url=source_url,
                verdict=verdict,
                upstream_license=upstream_license,
                image_document_id=image_document_id,
                evidence_id=crop_evidence_id,
                xywh_anchors=page_anchors or None,
            )
            if outcome is None:
                return await _fail(
                    session, investigation_id, lead_id, "persist_error:MediaMentionPersistFailed"
                )
            mention_count += 1
            identity_state, _claim_id, _claim_status = await _resolve_and_verify_mention(
                session,
                investigation_id,
                mention_id=outcome,
                target_query=query,
                text_excerpt=excerpt,
                evidence_id=crop_evidence_id,
                publication=publication if isinstance(publication, str) else None,
                published_at=_coerce_published_at(issued_at),
                page_urn=str(page_urn) if page_urn is not None else None,
                source_url=source_url if isinstance(source_url, str) else None,
            )
            if identity_state == ResolutionState.MATCH.value:
                identity_match_count += 1
            elif identity_state == ResolutionState.PROBABLE_MATCH.value:
                identity_probable_count += 1
            else:
                identity_unresolved_count += 1
        if stop_reason == "duplicate_results":
            break

    await repository.set_lead_status(session, investigation_id, lead_id, "COMPLETED")
    endpoints = ["nb_catalog"]
    if issues:
        endpoints += ["nb_contentfragments", "nb_contentsearch"]
    if dhlab_attempted:
        endpoints.append("nb_dhlab")
    await repository.bump_module_coverage(
        session,
        investigation_id,
        lead.scope_area,
        provider=PROVIDER,
        query_class=query_class.value,
        endpoints=endpoints,
        counters={
            "candidate_count": candidate_count,
            "located_count": located_count,
            "concordance_count": concordance_count,
            "fulltext_count": fulltext_count,
            "restricted_count": restricted_count,
            "fetched_count": page_fetch_count,
            "content_fragment_error_count": content_fragment_errors,
            "iiif_error_count": iiif_errors,
            "concordance_error_count": concordance_errors,
            "crop_unavailable_count": crop_skipped,
            "identity_match_count": identity_match_count,
            "identity_probable_count": identity_probable_count,
            "identity_unresolved_count": identity_unresolved_count,
        },
        time_from=earliest_issued.isoformat() if earliest_issued else None,
        time_to=latest_issued.isoformat() if latest_issued else None,
    )
    bridged_count, bridged_blocked = await bridge_original_urls(
        session, investigation_id, query=query, issues=all_issues
    )
    await repository._audit(
        session,
        investigation_id,
        "LEAD_EXECUTED",
        {
            "lead_id": str(lead_id),
            "status": "COMPLETED",
            "provider": PROVIDER,
            "query": query,
            "candidate_count": candidate_count,
            "located_count": located_count,
            "concordance_count": concordance_count,
            "mention_count": mention_count,
            "restricted_count": restricted_count,
            "page_fetch_count": page_fetch_count,
            "page_fetch_blocked": page_fetch_blocked,
            "crop_count": crop_count,
            "crop_skipped": crop_skipped,
            "content_fragment_errors": content_fragment_errors,
            "iiif_errors": iiif_errors,
            "concordance_errors": concordance_errors,
            "identity_match_count": identity_match_count,
            "identity_probable_count": identity_probable_count,
            "identity_unresolved_count": identity_unresolved_count,
            "duplicate_skips": duplicate_skips,
            "stop_reason": stop_reason,
            "bridged_count": bridged_count,
            "bridged_blocked": bridged_blocked,
        },
    )
    return "COMPLETED"


def collect_original_urls(issues: list[Any]) -> list[str]:
    """Collect fetchable original-article URLs from issue candidates.

    Pure function: keeps http(s) URLs with a hostname, drops catalog URLs,
    URNs, relative paths and non-web schemes, deduplicates preserving order
    and caps at ``MAX_ORIGINAL_URL_BRIDGES``. Never touches network or SQL.
    """
    urls: list[str] = []
    for issue in issues or []:
        if len(urls) >= MAX_ORIGINAL_URL_BRIDGES:
            break
        cleaned = parse_original_url(_field(issue, "original_url"))
        if cleaned is not None and cleaned not in urls:
            urls.append(cleaned)
    return urls


def build_original_url_lead(url: str, *, query: str, publication: str | None) -> Lead:
    """Build the gated ``web_document_fetch`` proposal for one original URL.

    Pure constructor: the lead always passes ``propose_lead`` admission
    (deterministic gate + audit) before it can run, under ``WEB_MEDIA`` at
    relation depth 0 with a ``DIRECT_SOURCE_LOOKUP`` trigger.
    """
    source = f" ({publication})" if publication else ""
    return Lead(
        lead_type="web_document_fetch",
        value={"url": url},
        reason=f"Original nettavis-URL fra NB-treff{source} for '{query}'",
        priority=0.5,
        depth=0,
        scope_area=ScopeModule.WEB_MEDIA,
        trigger_type=TriggerType.DIRECT_SOURCE_LOOKUP,
        information_need=(
            f"Hent original artikkel bak NB-treffet for '{query}' "
            "gjennom eksisterende safe fetcher"
        ),
        relation_depth=0,
    )


async def bridge_original_urls(
    session: AsyncSession,
    investigation_id: UUID,
    *,
    query: str,
    issues: list[Any],
) -> tuple[int, int]:
    """Propose gated ``web_document_fetch`` leads for NB original URLs.

    Returns ``(admitted, blocked)``. Every proposal passes the deterministic
    lead gate (refusals land BLOCKED with a reason and audit, never silently
    dropped). URLs already proposed in any status are skipped so reruns are
    idempotent. This is the documented exception to "executors never
    propose": the bridge performs no fetch itself and cannot bypass the
    gate — ``propose_lead`` IS the gate, and trigger evaluation happens in
    the research loop before any execution.
    """
    urls = collect_original_urls(issues)
    if not urls:
        return 0, 0
    rows = (
        await session.execute(
            text(
                "SELECT value FROM leads "
                "WHERE investigation_id = :id AND lead_type = 'web_document_fetch'"
            ),
            {"id": investigation_id},
        )
    ).mappings().all()
    known: set[str] = set()
    for row in rows:
        value = row["value"]
        if isinstance(value, dict):
            existing = value.get("url")
            if isinstance(existing, str) and existing.strip():
                known.add(existing.strip())
    admitted = 0
    blocked = 0
    for url in urls:
        if url in known:
            continue
        known.add(url)
        publication = None
        for issue in issues or []:
            if parse_original_url(_field(issue, "original_url")) == url:
                name = _field(issue, "publication")
                publication = name if isinstance(name, str) else None
                break
        _lead_id, status = await repository.propose_lead(
            session,
            investigation_id,
            build_original_url_lead(url, query=query, publication=publication),
        )
        if status == "PENDING":
            admitted += 1
        else:
            blocked += 1
    return admitted, blocked


async def _persist_mention(
    session: AsyncSession,
    investigation_id: UUID,
    lead_id: UUID,
    persist: Any,
    *,
    target_query: str,
    publication: Any,
    published_at: Any,
    page_number: int | None,
    issue_urn: Any,
    page_urn: str | None,
    headline: None,
    summary: None,
    text_excerpt: str | None,
    text_availability: str,
    source_url: Any,
    verdict: NBAccessVerdict,
    upstream_license: str | None,
    image_document_id: UUID | None = None,
    evidence_id: UUID | None = None,
    xywh_anchors: list[str] | None = None,
) -> Any | None:
    """Persist one mention via the canonical contract; None on store error."""
    try:
        result = persist(
            session,
            investigation_id=investigation_id,
            target_query=target_query,
            publication=publication if isinstance(publication, str) else None,
            published_at=_coerce_published_at(published_at),
            page_number=page_number,
            issue_urn=issue_urn if isinstance(issue_urn, str) else None,
            page_urn=page_urn,
            headline=headline,
            summary=summary,
            text_excerpt=text_excerpt,
            text_availability=text_availability,
            identity_state="UNRESOLVED",
            source_url=source_url if isinstance(source_url, str) else None,
            access_class=verdict.access_class,
            license_code=verdict.license_code or upstream_license,
            image_document_id=image_document_id,
            image_embeddable=bool(verdict.allow_report_embed),
            evidence_id=evidence_id,
            xywh_anchors=xywh_anchors,
        )
        if hasattr(result, "__await__"):
            return await result
        return result
    except Exception:
        return None


async def _resolve_and_verify_mention(
    session: AsyncSession,
    investigation_id: UUID,
    *,
    mention_id: UUID,
    target_query: str,
    text_excerpt: str | None,
    evidence_id: UUID | None,
    publication: str | None,
    published_at: date | None,
    page_urn: str | None,
    source_url: str | None,
) -> tuple[str, UUID | None, str | None]:
    """Resolve a persisted mention and bridge corroborated hits into claims.

    Name-only hits stay UNRESOLVED. MATCH evidence is linked as SUPPORTS;
    PROBABLE_MATCH evidence is linked only as PARTIAL/context. The canonical
    verifier then computes the claim status from the real evidence row.
    """
    from apps.api.app.repositories import claims_evidence
    from apps.api.app.repositories import media_mentions as mention_store
    from apps.api.app.services.verifier import verify_claim

    investigation = await repository.get_investigation_record(session, investigation_id)
    aliases = await load_verified_aliases(session, investigation_id)
    result = resolve_media_identity(
        investigation.target,
        target_query=target_query,
        text_excerpt=text_excerpt,
        verified_aliases=tuple(aliases),
    )
    await mention_store.update_media_mention_identity(
        session,
        mention_id,
        identity_state=result.state.value,
    )
    await repository._audit(
        session,
        investigation_id,
        "MEDIA_IDENTITY_EVALUATED",
        {
            "mention_id": str(mention_id),
            "state": result.state.value,
            "score": result.score,
            "reasons": list(result.reasons),
            "target_query": target_query,
        },
    )

    if evidence_id is None or result.state not in {
        ResolutionState.MATCH,
        ResolutionState.PROBABLE_MATCH,
    }:
        return result.state.value, None, None

    evidence_role = (
        "SUPPORTS" if result.state == ResolutionState.MATCH else "PARTIAL"
    )
    claim_id = await claims_evidence.upsert_claim(
        session,
        investigation_id,
        None,
        "media_mention",
        {
            "target_query": target_query,
            "identity_state": result.state.value,
            "publication": publication,
            "published_at": published_at.isoformat() if published_at else None,
            "page_urn": page_urn,
            "source_url": source_url,
        },
        ClaimStatus.UNVERIFIED_LEAD.value,
        [evidence_id],
        evidence_role,
    )
    verification = await verify_claim(session, investigation_id, claim_id)
    await repository._audit(
        session,
        investigation_id,
        "MEDIA_CLAIM_VERIFIED",
        {
            "mention_id": str(mention_id),
            "claim_id": str(claim_id),
            "identity_state": result.state.value,
            "claim_status": verification.status.value,
        },
    )
    return result.state.value, claim_id, verification.status.value


async def _extract_and_persist_crop(
    session: AsyncSession,
    investigation_id: UUID,
    *,
    item_id: str | None,
    issue_urn: str | None,
    page_urn: str | None,
    page_number: int | None,
    publication: str | None,
    issued_at: Any,
    source_url: str | None,
    query: str,
    anchors: list[str],
    page_bytes: bytes,
    verdict: NBAccessVerdict,
    upstream_license: str | None,
    page_ocr_fn: PageOcrFn | None = None,
    crop_ocr_fn: PageOcrFn | None = None,
) -> tuple[UUID | None, str | None, UUID | None]:
    """Best-effort permitted crop: ``(image_document_id, crop_text, evidence_id)``.

    Returns ``(None, None, None)`` whenever the crop is not permitted, not
    anchored, unvalidated, or technically unavailable (missing OCR stack,
    unpersistable bytes, database error). A skipped crop never fails the
    lead: the mention still persists with metadata/lawful context only.
    Broad ``except`` clauses are deliberate here — every failure mode below
    degrades to "no crop", never to a bypass or a crash.
    """
    if page_urn is None or not verdict.allow_derived_crop or not anchors:
        return None, None, None
    try:
        extraction = extract_permitted_article(
            page_bytes,
            page_urn=page_urn,
            anchor_xywh=list(anchors),
            target_expression=query,
            page_ocr_fn=page_ocr_fn,
            crop_ocr_fn=crop_ocr_fn,
        )
    except NBExtractError:
        return None, None, None
    except Exception:
        return None, None, None
    if not extraction.target_validated or not extraction.crop_text:
        return None, None, None
    try:
        _crop_digest, crop_key = store_raw_bytes(extraction.crop_bytes)
    except Exception:
        return None, None, None
    extraction.region.crop_storage_key = crop_key
    try:
        document_id, evidence_id = await _persist_crop_document(
            session,
            investigation_id,
            item_id=item_id,
            issue_urn=issue_urn,
            page_urn=page_urn,
            page_number=page_number,
            publication=publication,
            issued_at=issued_at,
            source_url=source_url,
            query=query,
            anchors=list(anchors),
            verdict=verdict,
            upstream_license=upstream_license,
            extraction=extraction,
        )
    except Exception:
        return None, None, None
    return document_id, extraction.crop_text, evidence_id


async def _persist_crop_document(
    session: AsyncSession,
    investigation_id: UUID,
    *,
    item_id: str | None,
    issue_urn: str | None,
    page_urn: str,
    page_number: int | None,
    publication: str | None,
    issued_at: Any,
    source_url: str | None,
    query: str,
    anchors: list[str],
    verdict: NBAccessVerdict,
    upstream_license: str | None,
    extraction: Any,
) -> tuple[UUID, UUID]:
    """Persist a validated crop as Document + Evidence with full NB locator.

    Returns ``(document_id, evidence_id)``. The evidence locator preserves
    item ID, issue/page URN, page number, query, ``xywh`` anchors, exact
    crop geometry, both hashes, publication, issue date and upstream
    access/license fields (docs/NATIONAL_LIBRARY.md "Provenance").
    """
    from apps.api.app.domain.models import SourceRegistryRecord
    from apps.api.app.repositories import claims_evidence

    region = extraction.region
    crop_text = extraction.crop_text or ""
    excerpt = crop_text[:2000] or None
    locator = {
        "provider": PROVIDER,
        "item_id": item_id,
        "issue_urn": issue_urn,
        "page_urn": page_urn,
        "page_number": page_number,
        "query": query,
        "xywh": list(anchors),
        "crop": {"x": region.x, "y": region.y, "w": region.w, "h": region.h},
        "page": {"width": region.page_width, "height": region.page_height},
        "page_sha256": region.page_sha256,
        "crop_sha256": region.crop_sha256,
        "crop_storage_key": region.crop_storage_key,
        "publication": publication,
        "issued_at": str(issued_at) if issued_at is not None else None,
        "access_class": verdict.access_class,
        "license_code": verdict.license_code or upstream_license,
        "source_url": source_url,
        "ocr_lang": "nor",
    }
    structured_value = {
        "crop": locator["crop"],
        "page": locator["page"],
        "hashes": {
            "page_sha256": region.page_sha256,
            "crop_sha256": region.crop_sha256,
        },
        "target_validated": bool(extraction.target_validated),
        "ocr_lang": "nor",
    }
    source = SourceRegistryRecord(
        id="nb_catalog",
        name="Nasjonalbiblioteket Catalog",
        evidence_tier=2,
        access_class=f"NB_{verdict.access_class}",
        base_url="https://api.nb.no/catalog/v1",
        license=verdict.license_code or upstream_license,
        metadata={"provider": PROVIDER},
    )
    await claims_evidence.upsert_source(session, source)
    canonical = source_url or f"nb:{page_urn}"
    document_id = await claims_evidence.upsert_document(
        session,
        source_id=source.id,
        original_url=canonical,
        canonical_url=canonical,
        mime_type="image/png",
        sha256=region.crop_sha256 or "",
        raw_storage_key=region.crop_storage_key,
        extracted_text=crop_text or None,
        parser_metadata={
            "provider": PROVIDER,
            "locator": locator,
            "query": query,
        },
        fetched_at=None,
    )
    await claims_evidence.attach_document(
        session, investigation_id, document_id, reason="nb_media_crop"
    )
    evidence_id = await claims_evidence.store_evidence(
        session,
        document_id,
        "nb_article_crop",
        locator,
        excerpt,
        structured_value,
    )
    return document_id, evidence_id
