from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

from apps.api.app.domain.identifiers import normalize_orgnr


class TargetType(StrEnum):
    PERSON = "person"
    ORGANIZATION = "organization"
    COMPANY = "company"
    DOMAIN = "domain"


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
    type: TargetType
    name: str = Field(min_length=1, max_length=500)
    birth_date: date | None = None
    birth_year: int | None = Field(default=None, ge=1900, le=2100)
    place: str | None = Field(default=None, max_length=500)
    known_orgnrs: list[str] = Field(default_factory=list)
    known_organizations: list[str] = Field(default_factory=list)

    @field_validator("known_orgnrs")
    @classmethod
    def validate_known_orgnrs(cls, values: list[str]) -> list[str]:
        return [normalize_orgnr(value) for value in values]

    @model_validator(mode="after")
    def check_birth_fields(self) -> "TargetInput":
        if self.birth_date and self.birth_year and self.birth_date.year != self.birth_year:
            raise ValueError("birth_date and birth_year must describe the same year")
        if self.type != TargetType.PERSON and (self.birth_date or self.birth_year):
            raise ValueError("birth_date and birth_year are only valid for person targets")
        return self


class InvestigationCreate(BaseModel):
    target: TargetInput
    purpose: str = Field(min_length=3, max_length=1000)
    legal_basis_note: str | None = Field(default=None, max_length=2000)


class InvestigationRecord(BaseModel):
    id: UUID
    target: TargetInput
    purpose: str
    legal_basis_note: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime


class InvestigationEntityRecord(BaseModel):
    id: UUID
    schema: str
    canonical_name: str | None = None
    attributes: dict[str, Any]
    resolution_state: ResolutionState


class InvestigationClaimRecord(BaseModel):
    id: UUID
    subject_entity_id: UUID | None = None
    predicate: str
    value: Any | None = None
    status: ClaimStatus
    created_at: datetime


class InvestigationDetail(InvestigationRecord):
    entities: list[InvestigationEntityRecord] = Field(default_factory=list)
    claims: list[InvestigationClaimRecord] = Field(default_factory=list)


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


class BrregAddress(BaseModel):
    address_lines: list[str] = Field(default_factory=list)
    postal_code: str | None = None
    postal_place: str | None = None
    municipality: str | None = None
    municipality_number: str | None = None
    country: str | None = None
    country_code: str | None = None


class BrregHistoricalName(BaseModel):
    name: str
    valid_from: date | None = None
    valid_to: date | None = None


class BrregOrganization(BaseModel):
    organization_number: str
    name: str
    organization_form_code: str | None = None
    organization_form_description: str | None = None
    registered_at: date | None = None
    foundation_date: date | None = None
    deleted_at: date | None = None
    business_address: BrregAddress | None = None
    postal_address: BrregAddress | None = None
    website: str | None = None
    primary_industry_code: str | None = None
    primary_industry_description: str | None = None
    historical_names: list[BrregHistoricalName] = Field(default_factory=list)
    status_flags: dict[str, bool] = Field(default_factory=dict)


class BrregIngestResult(BaseModel):
    investigation_id: UUID
    entity_id: UUID
    document_id: UUID
    evidence_id: UUID
    claim_ids: list[UUID]
    organization: BrregOrganization
