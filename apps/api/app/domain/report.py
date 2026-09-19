"""Typed report document contract (AQ-027).

ReportDocument is the single source of truth both renderers consume: the
HTML page and the PDF bytes describe the same findings, coverage and
citations. Findings carry per-claim citations; unverified leads are listed
separately and never presented as findings; context-only entities appear by
name only, never as background-checked subjects.

Media mentions (AQ-031, Nasjonalbiblioteket) are part of the same document:
each mention carries publication metadata, the lawful text actually stored
(``text_availability``), identity resolution state, NB locators and
access/license metadata. A mention is never presented as identity proof, and
restricted content is rendered as metadata + direct NB link, never as a
broken image or fabricated full text.
"""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from apps.api.app.domain.models import ClaimStatus
from apps.api.app.domain.nb_media import NBTextAvailability


class ReportCitation(BaseModel):
    """One clickable provenance step behind a finding.

    ``claim_id`` is set for claim findings. Media-mention citations carry
    the stored evidence/document locators without a claim, so ``claim_id``
    stays None there instead of pointing at a fabricated claim.
    """

    model_config = ConfigDict(extra="forbid")

    claim_id: UUID | None = None
    evidence_id: UUID | None = None
    document_id: UUID | None = None
    source_id: str | None = None
    excerpt: str | None = None
    url: str | None = None
    fetched_at: datetime | None = None
    sha256: str | None = None


class ReportFinding(BaseModel):
    """One claim with its verdict and citations."""

    model_config = ConfigDict(extra="forbid")

    predicate: str
    value: Any | None = None
    status: ClaimStatus
    subject_name: str | None = None
    citations: list[ReportCitation] = Field(default_factory=list)


class CoverageEntry(BaseModel):
    """One scope module's report outcome."""

    model_config = ConfigDict(extra="forbid")

    module: str
    enabled: bool
    status: str
    outcome: str
    stop_reason: str | None = None
    providers: list[str] = Field(default_factory=list)
    query_count: int = 0
    document_count: int = 0
    endpoints: list[str] = Field(default_factory=list)
    query_classes: list[str] = Field(default_factory=list)
    candidate_count: int = 0
    located_count: int = 0
    concordance_count: int = 0
    fulltext_count: int = 0
    restricted_count: int = 0
    fetched_count: int = 0
    time_from: date | None = None
    time_to: date | None = None


class ContextEntity(BaseModel):
    """A context-only entity: name and schema, never a background check."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    entity_schema: str
    relation: str | None = None


class UnverifiedLead(BaseModel):
    """An open lead, visually and linguistically separate from findings."""

    model_config = ConfigDict(extra="forbid")

    predicate: str | None = None
    information_need: str
    reason: str | None = None


class MediaMention(BaseModel):
    """One stored NB/media mention: metadata, lawful text and access.

    Conservative contract: content fields stay ``None`` when nothing was
    lawfully stored. ``text_availability`` declares how much article text the
    mention actually carries (``FULL`` requires full text to be lawfully
    available and retrieved; DH-lab concordance is ``PARTIAL_CONTEXT``,
    never ``FULL``). ``identity_state`` is the resolution state of the
    mention candidate — an exact-name hit is never identity proof.
    ``xywh_anchors`` carries the correlated IIIF text anchors for the page
    (exact URN first, canvas fallback); empty when no anchors were stored.
    """

    model_config = ConfigDict(extra="forbid")

    publication: str | None = None
    published_at: date | None = None
    page_number: int | None = None
    headline: str | None = None
    summary: str | None = None
    text_excerpt: str | None = None
    text_availability: NBTextAvailability = NBTextAvailability.UNAVAILABLE
    identity_state: str | None = None
    issue_urn: str | None = None
    page_urn: str | None = None
    source_url: str | None = None
    access_class: str | None = None
    license_code: str | None = None
    image_document_id: UUID | None = None
    image_embeddable: bool = False
    target_query: str | None = None
    citations: list[ReportCitation] = Field(default_factory=list)
    xywh_anchors: list[str] = Field(default_factory=list)


class ReportDocument(BaseModel):
    """Complete report content; renderers add presentation only."""

    model_config = ConfigDict(extra="forbid")

    investigation_id: UUID
    target_name: str
    target_type: str
    purpose: str
    generated_at: datetime
    expansion_policy: str
    max_relation_depth: int
    scope_modules: list[str] = Field(default_factory=list)
    findings: list[ReportFinding] = Field(default_factory=list)
    media_mentions: list[MediaMention] = Field(default_factory=list)
    unverified_leads: list[UnverifiedLead] = Field(default_factory=list)
    context_entities: list[ContextEntity] = Field(default_factory=list)
    coverage: list[CoverageEntry] = Field(default_factory=list)
