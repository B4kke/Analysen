"""Typed, fail-closed models for the checked-in runtime configuration."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ModelProviderConfig(StrictModel):
    type: Literal["openai_compatible"]
    base_url_env: Literal["NIM_BASE_URL"]
    api_key_env: Literal["NIM_API_KEY"]


class ModelRoleConfig(StrictModel):
    primary: str = Field(min_length=1)
    fallback: str | None = None
    deep: str | None = None
    canary: str | None = None
    norwegian_fallback: str | None = None
    reasoning: bool | None = None
    json_mode: bool | None = None
    note: str | None = None


class ModelsConfig(StrictModel):
    provider: ModelProviderConfig
    roles: dict[str, ModelRoleConfig] = Field(min_length=1)
    routing: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_required_roles(self) -> "ModelsConfig":
        required = {
            "planner", "workhorse", "extractor", "verifier", "reporter", "vision", "embedding"
        }
        missing = required.difference(self.roles)
        if missing:
            raise ValueError(f"models config missing required roles: {sorted(missing)}")
        return self


class SourceConfig(StrictModel):
    enabled: bool
    access: Literal[
        "OPEN_NO_KEY",
        "PUBLIC_WEB",
        "PUBLIC_ACCESS",
        "OPEN_DOWNLOAD",
        "PUBLIC_WEB_DOWNLOAD",
        "MIXED_RIGHTS",
        "SELF_HOSTED",
        "ENTITLEMENT_REQUIRED",
        "PUBLIC_API_KEY_REQUIRED",
        "PUBLIC_REGISTRATION_REQUIRED",
        "API_KEY_REQUIRED",
        "DISABLED_BY_POLICY",
    ]
    evidence_tier: int | None = Field(default=None, ge=1, le=5)
    base_url: HttpUrl | None = None
    dhlab_base_url: HttpUrl | None = None
    endpoint: str | None = None
    url: HttpUrl | None = None
    reference: HttpUrl | None = None
    index_url: HttpUrl | None = None
    license: str | None = None
    reason: str | None = None
    contains_birth_date: bool | None = None
    contains_national_id: bool | None = None
    discovery_only: bool | None = None
    historical: bool | None = None
    base_url_env: str | None = None
    candidate: bool | None = None
    retention_policy: str | None = None
    rights_policy: str | None = None
    notes: list[str] | None = None

    @model_validator(mode="after")
    def validate_disabled_source(self) -> "SourceConfig":
        if not self.enabled and not self.reason:
            raise ValueError("disabled sources must document a reason")
        if self.enabled and self.access in {
            "ENTITLEMENT_REQUIRED",
            "PUBLIC_API_KEY_REQUIRED",
            "PUBLIC_REGISTRATION_REQUIRED",
            "API_KEY_REQUIRED",
            "DISABLED_BY_POLICY",
        }:
            raise ValueError(f"source access class {self.access} cannot be enabled")
        if self.discovery_only and self.evidence_tier is not None:
            raise ValueError("discovery-only sources cannot have an evidence tier")
        return self


class SourcesConfig(StrictModel):
    sources: dict[str, SourceConfig] = Field(min_length=1)


class CollectionPolicy(StrictModel):
    public_sources_only: Literal[True]
    no_auth_bypass: Literal[True]
    no_captcha_bypass: Literal[True]
    no_paywall_bypass: Literal[True]
    no_private_api_bypass: Literal[True]
    honor_domain_rate_limits: Literal[True]


class PrivacyPolicy(StrictModel):
    blocked_inferences: list[str] = Field(min_length=1)
    store_national_id_by_default: Literal[False]
    criminal_records_default_enabled: Literal[False]
    political_registry_default_enabled: Literal[False]
    personal_risk_score_allowed: Literal[False]


class PersonRoleAggregationPolicy(StrictModel):
    business_context_only: Literal[True]
    allow_voluntary_organization_roles_in_combined_person_overview: Literal[False]
    require_business_context_verification: Literal[True]
    source_note: str = Field(min_length=1)


class NorwayPolicy(StrictModel):
    person_role_aggregation: PersonRoleAggregationPolicy


class HighImpactPolicy(StrictModel):
    automated_decision_allowed: Literal[False]
    domains: list[str] = Field(min_length=1)


class CrawlerPolicy(StrictModel):
    allowed_schemes: list[Literal["http", "https"]] = Field(min_length=1)
    block_private_networks: Literal[True]
    max_redirects: int = Field(ge=0, le=20)
    default_domain_concurrency: int = Field(ge=1, le=100)
    default_domain_delay_seconds: float = Field(ge=0)


class InvestigationDefaults(StrictModel):
    max_depth: int = Field(ge=0)
    max_urls: int = Field(gt=0)
    max_documents: int = Field(gt=0)
    max_pages_per_domain: int = Field(gt=0)
    max_model_calls: int = Field(gt=0)
    require_human_review_for_probable_identity: bool


class PoliciesConfig(StrictModel):
    collection: CollectionPolicy
    privacy: PrivacyPolicy
    norway: NorwayPolicy
    high_impact: HighImpactPolicy
    crawler: CrawlerPolicy
    investigation_defaults: InvestigationDefaults

    @model_validator(mode="after")
    def validate_safety_policy(self) -> "PoliciesConfig":
        required = {"health", "religion", "ethnicity", "sexual_orientation", "political_opinion"}
        if not required.issubset(set(self.privacy.blocked_inferences)):
            raise ValueError("privacy policy must block sensitive inference categories")
        return self
