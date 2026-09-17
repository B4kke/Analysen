from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


class ResolutionState(StrEnum):
    MATCH = "MATCH"
    PROBABLE_MATCH = "PROBABLE_MATCH"
    UNRESOLVED = "UNRESOLVED"
    NOT_MATCH = "NOT_MATCH"


class ClaimStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    UNVERIFIED_LEAD = "UNVERIFIED_LEAD"


class TargetInput(BaseModel):
    type: str
    name: str
    birth_date: date | None = None
    birth_year: int | None = None
    place: str | None = None
    known_orgnrs: list[str] = Field(default_factory=list)
    known_organizations: list[str] = Field(default_factory=list)


class InvestigationCreate(BaseModel):
    target: TargetInput
    purpose: str = Field(min_length=3, max_length=1000)
    legal_basis_note: str | None = None


class SearchResult(BaseModel):
    url: HttpUrl
    title: str | None = None
    snippet: str | None = None
    provider: str
    rank: int | None = None


class EvidenceCandidate(BaseModel):
    source_id: str
    document_id: UUID | None = None
    locator_type: str
    locator: dict[str, Any]
    excerpt: str | None = None
    structured_value: Any | None = None


class ClaimCandidate(BaseModel):
    subject_ref: str
    predicate: str
    object_ref: str | None = None
    value: Any | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    evidence: list[EvidenceCandidate] = Field(min_length=1)


class Lead(BaseModel):
    lead_type: str
    value: Any
    reason: str
    priority: float = Field(ge=0, le=1)
    depth: int = Field(ge=0)
    originating_claim_id: UUID | None = None


class VerificationResult(BaseModel):
    status: ClaimStatus
    rationale: str
    supporting_evidence_ids: list[UUID] = Field(default_factory=list)
    contradicting_evidence_ids: list[UUID] = Field(default_factory=list)
    verified_at: datetime = Field(default_factory=datetime.utcnow)
