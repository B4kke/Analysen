"""Typed allowlist router mapping lead types to executor names (AQ-024)."""

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
