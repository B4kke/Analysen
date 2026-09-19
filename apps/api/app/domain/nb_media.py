"""Typed Nasjonalbiblioteket media contracts (AQ-031).

Canonical source: ``docs/NATIONAL_LIBRARY.md``. This module owns the typed
domain contracts for NB newspaper/media research. It performs no network I/O.

Core semantics enforced by these types:
- A catalog hit is a candidate, never identity proof.
- ``contentfragments`` output is a page locator, never article text.
- DH-lab concordance output is ``PARTIAL_CONTEXT``, never ``FULL`` text.
- Rights/access is decided per item and fails closed.
"""

from datetime import date
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class NBAccessState(StrEnum):
    """Conservative normalized item-level access states."""

    PUBLIC_REUSE = "PUBLIC_REUSE"
    PUBLIC_VIEW_ONLY = "PUBLIC_VIEW_ONLY"
    LIBRARY_ONLY = "LIBRARY_ONLY"
    NB_ONLY = "NB_ONLY"
    UNKNOWN = "UNKNOWN"


class NBTextAvailability(StrEnum):
    """How much lawful article text a media mention actually carries."""

    FULL = "FULL"
    PARTIAL_CONTEXT = "PARTIAL_CONTEXT"
    UNAVAILABLE = "UNAVAILABLE"


class NBIdentityState(StrEnum):
    """Identity resolution state for a media mention candidate.

    Mirrors the conservative entity-resolution semantics: an exact-name
    newspaper hit starts ``UNRESOLVED`` and name alone can never reach
    ``MATCH``.
    """

    MATCH = "MATCH"
    PROBABLE_MATCH = "PROBABLE_MATCH"
    UNRESOLVED = "UNRESOLVED"
    NOT_MATCH = "NOT_MATCH"


class NBSearchCandidate(BaseModel):
    """One issue candidate from a Catalog FULL_TEXT_SEARCH discovery pass."""

    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(min_length=1, max_length=500)
    publication: str | None = Field(default=None, max_length=500)
    issued_at: date | None = None
    issue_urn: str | None = Field(default=None, max_length=500)
    title: str | None = Field(default=None, max_length=1000)
    rank: int = Field(ge=1)
    access_metadata: dict[str, Any] = Field(default_factory=dict)
    original_url: str | None = Field(default=None, max_length=2000)


class NBSearchResponse(BaseModel):
    """Bounded result envelope for a Catalog newspaper search."""

    model_config = ConfigDict(extra="forbid")

    query: str
    total: int = Field(ge=0)
    returned: int = Field(ge=0)
    capped: bool = False
    candidates: list[NBSearchCandidate] = Field(default_factory=list)


class NBPageLocator(BaseModel):
    """A page location hint derived from contentfragments.

    Deliberately carries no text field: contentfragments output is a
    locator, never article text (live regression 2026-09-18 showed even
    large ``fragSize`` values returning only ``... <em>name</em> ...``).
    """

    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(min_length=1, max_length=500)
    issue_urn: str | None = Field(default=None, max_length=500)
    page_urn: str = Field(min_length=1, max_length=500)
    page_number: int | None = Field(default=None, ge=1)
    query: str | None = Field(default=None, max_length=1000)


class NBTextAnchor(BaseModel):
    """One exact OCR token anchor from IIIF Content Search (xywh)."""

    model_config = ConfigDict(extra="forbid")

    page_urn: str = Field(min_length=1, max_length=500)
    xywh: str = Field(min_length=1, max_length=100)
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(ge=1)
    h: int = Field(ge=1)
    target_uri: str | None = Field(default=None, max_length=2000)
    query: str | None = Field(default=None, max_length=1000)


class NBPageHit(BaseModel):
    """One page with its IIIF text anchors for a query."""

    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(min_length=1, max_length=500)
    issue_urn: str | None = Field(default=None, max_length=500)
    page_urn: str = Field(min_length=1, max_length=500)
    page_number: int | None = Field(default=None, ge=1)
    query: str = Field(min_length=1, max_length=1000)
    anchors: list[NBTextAnchor] = Field(default_factory=list)
    thumbnail_url: str | None = Field(default=None, max_length=2000)


class NBConcreteConcordance(BaseModel):
    """One bounded keyword-in-context row from DH-lab ``/conc``.

    Always ``PARTIAL_CONTEXT``: lawful context excerpt, never full text.
    """

    model_config = ConfigDict(extra="forbid")

    urn: str = Field(min_length=1, max_length=500)
    before: str | None = Field(default=None, max_length=2000)
    match: str | None = Field(default=None, max_length=1000)
    after: str | None = Field(default=None, max_length=2000)
    text_availability: NBTextAvailability = NBTextAvailability.PARTIAL_CONTEXT


class NBAccessDecision(BaseModel):
    """Normalized per-item rights/access decision (fails closed)."""

    model_config = ConfigDict(extra="forbid")

    state: NBAccessState
    upstream: dict[str, Any] = Field(default_factory=dict)
    allow_metadata: bool = False
    allow_context: bool = False
    allow_full_text_storage: bool = False
    allow_page_fetch: bool = False
    allow_derived_crop: bool = False
    allow_report_embed: bool = False
    reason: str = Field(min_length=1, max_length=2000)


class MediaMentionCandidate(BaseModel):
    """An exact-name newspaper occurrence, not identity proof.

    Identity starts ``UNRESOLVED``; promotion to ``MATCH``/``PROBABLE_MATCH``
    requires corroboration through the entity-resolution system.
    """

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=1000)
    target_name: str | None = Field(default=None, max_length=500)
    publication: str | None = Field(default=None, max_length=500)
    published_at: date | None = None
    page_number: int | None = Field(default=None, ge=1)
    item_id: str | None = Field(default=None, max_length=500)
    issue_urn: str | None = Field(default=None, max_length=500)
    page_urn: str | None = Field(default=None, max_length=500)
    text_availability: NBTextAvailability = NBTextAvailability.UNAVAILABLE
    context_excerpt: str | None = Field(default=None, max_length=5000)
    headline: str | None = Field(default=None, max_length=1000)
    body: str | None = Field(default=None, max_length=20000)
    caption: str | None = Field(default=None, max_length=2000)
    identity_state: NBIdentityState = NBIdentityState.UNRESOLVED
    access_state: NBAccessState = NBAccessState.UNKNOWN
    license_code: str | None = Field(default=None, max_length=500)
    source_url: str | None = Field(default=None, max_length=2000)
    evidence_ids: list[UUID] = Field(default_factory=list)
    document_ids: list[UUID] = Field(default_factory=list)
