"""Typed report document contract (AQ-027).

ReportDocument is the single source of truth both renderers consume: the
HTML page and the PDF bytes describe the same findings, coverage and
citations. Findings carry per-claim citations; unverified leads are listed
separately and never presented as findings; context-only entities appear by
name only, never as background-checked subjects.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from apps.api.app.domain.models import ClaimStatus


class ReportCitation(BaseModel):
    """One clickable provenance step behind a finding."""

    model_config = ConfigDict(extra="forbid")

    claim_id: UUID
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
    unverified_leads: list[UnverifiedLead] = Field(default_factory=list)
    context_entities: list[ContextEntity] = Field(default_factory=list)
    coverage: list[CoverageEntry] = Field(default_factory=list)
