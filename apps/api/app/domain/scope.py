"""Typed investigation permissions and coverage; no model can grant itself scope."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ScopeModule(StrEnum):
    WEB_MEDIA = "WEB_MEDIA"
    BUSINESS_ROLES = "BUSINESS_ROLES"
    COMPANY_NETWORK = "COMPANY_NETWORK"
    FINANCIALS = "FINANCIALS"
    ANNOUNCEMENTS_STATUS = "ANNOUNCEMENTS_STATUS"
    HISTORICAL_WEB = "HISTORICAL_WEB"
    DOMAINS_DIGITAL = "DOMAINS_DIGITAL"
    PUBLIC_PROFILES = "PUBLIC_PROFILES"
    SANCTIONS = "SANCTIONS"


class ExpansionPolicy(StrEnum):
    CONTEXT_ONLY = "CONTEXT_ONLY"
    DIRECT_RELATIONS = "DIRECT_RELATIONS"
    MATERIAL_RELATIONS = "MATERIAL_RELATIONS"


class ExpansionState(StrEnum):
    TARGET = "TARGET"
    MATERIAL = "MATERIAL"
    CONTEXT_ONLY = "CONTEXT_ONLY"
    BLOCKED = "BLOCKED"
    RESEARCHED = "RESEARCHED"


class TriggerType(StrEnum):
    IDENTITY_AMBIGUITY = "IDENTITY_AMBIGUITY"
    NEW_VERIFIED_ALIAS = "NEW_VERIFIED_ALIAS"
    MATERIAL_RELATION = "MATERIAL_RELATION"
    WEAK_SOURCE_ONLY = "WEAK_SOURCE_ONLY"
    CONTRADICTION = "CONTRADICTION"
    TEMPORAL_GAP = "TEMPORAL_GAP"
    FINANCIAL_ANOMALY = "FINANCIAL_ANOMALY"
    DOCUMENT_QUALITY = "DOCUMENT_QUALITY"
    DOMAIN_RELEVANCE = "DOMAIN_RELEVANCE"
    MEDIA_CORROBORATION = "MEDIA_CORROBORATION"
    SANCTIONS_CANDIDATE = "SANCTIONS_CANDIDATE"


class QueryClass(StrEnum):
    IDENTIFIER_EXACT = "IDENTIFIER_EXACT"
    ENTITY_ALIAS_EXACT = "ENTITY_ALIAS_EXACT"
    PERSON_COMPANY_RELATION = "PERSON_COMPANY_RELATION"
    TEMPORAL = "TEMPORAL"
    CONTRADICTION = "CONTRADICTION"
    DOMAIN = "DOMAIN"
    SOURCE_CONSTRAINED = "SOURCE_CONSTRAINED"
    MEDIA_CORROBORATION = "MEDIA_CORROBORATION"
    DISCOVERY_BROAD = "DISCOVERY_BROAD"


class ModuleStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"


class ScopeSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    scope_modules: list[ScopeModule] = Field(default_factory=list)
    expansion_policy: ExpansionPolicy = ExpansionPolicy.CONTEXT_ONLY
    max_relation_depth: int = Field(default=0, ge=0, le=3)

    @field_validator("scope_modules")
    @classmethod
    def unique_modules(cls, modules: list[ScopeModule]) -> list[ScopeModule]:
        if len(set(modules)) != len(modules):
            raise ValueError("scope_modules must not contain duplicates")
        return modules


class ScopeUpdate(ScopeSettings):
    # A scope update replaces the complete permission set.
    scope_modules: list[ScopeModule]
    expansion_policy: ExpansionPolicy
    max_relation_depth: int = Field(ge=0, le=3)
    reason: str = Field(min_length=3, max_length=1000)


class Coverage(BaseModel):
    providers: list[str] = Field(default_factory=list)
    query_classes: list[QueryClass] = Field(default_factory=list)
    query_count: int = Field(default=0, ge=0)
    document_count: int = Field(default=0, ge=0)
    gaps: list[str] = Field(default_factory=list)
    unavailable_sources: list[str] = Field(default_factory=list)


class InvestigationModuleRecord(BaseModel):
    module: ScopeModule
    enabled: bool
    status: ModuleStatus
    coverage: Coverage = Field(default_factory=Coverage)
    stop_reason: str | None = None


class SearchMetadata(BaseModel):
    originating_lead_id: UUID
    scope_area: ScopeModule
    query_class: QueryClass
    information_need: str = Field(min_length=3, max_length=2000)
    reason: str = Field(min_length=3, max_length=2000)
