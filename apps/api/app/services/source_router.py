"""Typed allowlist router mapping lead types to executor names (AQ-024)."""

from apps.api.app.core.config_models import SourcesConfig

EXECUTOR_ROUTES: dict[str, str] = {
    "brreg_organization_lookup": "brreg",
    "searxng_discovery": "searxng",
    "web_document_fetch": "web_fetch",
    "pdf_document_process": "pdf",
    "nb_newspaper_search": "nb_media",
}


class UnknownLeadType(ValueError):
    """Raised when a lead type is not in the allowlist."""


def route_lead(lead_type: str) -> str:
    """Return the executor name for an allowlisted lead type."""
    try:
        return EXECUTOR_ROUTES[lead_type]
    except KeyError:
        raise UnknownLeadType(lead_type) from None


def supported_lead_types() -> frozenset[str]:
    """Return the allowlisted lead types."""
    return frozenset(EXECUTOR_ROUTES.keys())


# Generic document/PDF processing has no independent provider switch in sources.yaml.
# Its scope, fetch policy and provenance checks remain mandatory.
EXECUTOR_SOURCE_IDS: dict[str, str | None] = {
    "brreg": "brreg_entities",
    "searxng": "searxng",
    "web_fetch": None,
    "pdf": None,
    "nb_media": "national_library_no",
}


def executor_source_enabled(executor: str, sources: SourcesConfig) -> bool:
    """Missing or disabled named providers fail closed; unknown routes never run."""
    if executor not in EXECUTOR_SOURCE_IDS:
        return False
    source_id = EXECUTOR_SOURCE_IDS[executor]
    if source_id is None:
        return True
    return named_source_enabled(source_id, sources)


def named_source_enabled(source_id: str, sources: SourcesConfig) -> bool:
    source = sources.sources.get(source_id)
    return source is not None and source.enabled
