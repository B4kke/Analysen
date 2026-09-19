"""Per-item NB rights/access normalization (AQ-031).

Pure and deterministic: no network. Fails closed -- unknown or incomplete
rights metadata never upgrades to reuse or embed rights, and
``viewability=ALL`` alone never grants report embedding.
"""

from typing import Any

from apps.api.app.domain.nb_media import NBAccessDecision, NBAccessState

_OPEN_LICENSE_TOKENS = frozenset(
    {
        "cc0",
        "cc-0",
        "public",
        "pd",
        "publicdomain",
        "public-domain",
        "nocopyright",
        "no-copyright",
        "open",
    }
)

_EVERYWHERE_TOKENS = frozenset({"everywhere", "all", "public", "open", "everyone"})
_LIBRARY_TOKENS = frozenset({"library", "libraries", "bibliotek", "biblioteket"})
_NB_ONLY_TOKENS = frozenset({"nb", "nb_only", "nb-only", "lesesal", "readingroom", "reading-room"})


class NBAccessDenied(Exception):
    """Raised when a rights-gated operation is attempted on a denied item."""

    def __init__(self, message: str, *, state: NBAccessState) -> None:
        super().__init__(message)
        self.state = state


def _normalized_lookup(metadata: dict[str, Any]) -> dict[str, Any]:
    """Case-insensitive key lookup preserving original values."""
    merged: dict[str, Any] = {}
    for key, value in metadata.items():
        merged[str(key).lower()] = value
    return merged


def _pick(lookup: dict[str, Any], *names: str) -> Any:
    for name in names:
        value = lookup.get(name.lower())
        if value not in (None, ""):
            return value
    return None


def _token(value: Any) -> str:
    return str(value).strip().lower()


def _license_is_open(license_value: Any, rights_uri: Any) -> bool:
    license_token = _token(license_value) if license_value is not None else ""
    rights_token = _token(rights_uri) if rights_uri is not None else ""
    combined = f"{license_token} {rights_token}"
    if "creativecommons.org/publicdomain" in rights_token or "creativecommons.org/cc0" in (
        license_token + " " + rights_token
    ):
        return True
    return any(token in combined for token in _OPEN_LICENSE_TOKENS)


def decide_access(item_metadata: dict[str, Any]) -> NBAccessDecision:
    """Normalize upstream NB access fields into a conservative decision."""
    metadata = dict(item_metadata or {})
    lookup = _normalized_lookup(metadata)

    access_allowed_from = _pick(lookup, "accessAllowedFrom", "access_allowed_from", "access")
    viewability = _pick(lookup, "viewability")
    is_public_domain = _pick(lookup, "isPublicDomain", "is_public_domain", "publicDomain")
    license_value = _pick(lookup, "license", "licenseCode", "license_code")
    rights_uri = _pick(lookup, "rights", "rightsUri", "rights_uri", "rightsURI")
    attribution = _pick(lookup, "attribution")

    upstream: dict[str, Any] = {}
    if access_allowed_from is not None:
        upstream["accessAllowedFrom"] = access_allowed_from
    if viewability is not None:
        upstream["viewability"] = viewability
    if is_public_domain is not None:
        upstream["isPublicDomain"] = is_public_domain
    if license_value is not None:
        upstream["license"] = license_value
    if rights_uri is not None:
        upstream["rightsUri"] = rights_uri
    if attribution is not None:
        upstream["attribution"] = attribution

    access_token = _token(access_allowed_from) if access_allowed_from is not None else ""
    viewability_token = (
        str(viewability).strip().upper() if viewability is not None else ""
    )
    public_domain_true = is_public_domain is True or _token(is_public_domain) == "true"
    public_domain_false = is_public_domain is False or _token(is_public_domain) == "false"
    open_license = _license_is_open(license_value, rights_uri)

    if not upstream:
        return NBAccessDecision(
            state=NBAccessState.UNKNOWN,
            upstream={},
            allow_metadata=True,
            allow_context=False,
            allow_full_text_storage=False,
            allow_page_fetch=False,
            allow_derived_crop=False,
            allow_report_embed=False,
            reason="unknown-or-incomplete rights metadata: fail closed",
        )

    # Public domain with no contradicting restriction: reusable.
    if public_domain_true and access_token not in _LIBRARY_TOKENS | _NB_ONLY_TOKENS:
        return NBAccessDecision(
            state=NBAccessState.PUBLIC_REUSE,
            upstream=upstream,
            allow_metadata=True,
            allow_context=True,
            allow_full_text_storage=True,
            allow_page_fetch=True,
            allow_derived_crop=True,
            allow_report_embed=True,
            reason="isPublicDomain=true with no library-only restriction",
        )

    # Explicit open license on everywhere-accessible material: reusable.
    if open_license and access_token in _EVERYWHERE_TOKENS and not public_domain_false:
        return NBAccessDecision(
            state=NBAccessState.PUBLIC_REUSE,
            upstream=upstream,
            allow_metadata=True,
            allow_context=True,
            allow_full_text_storage=True,
            allow_page_fetch=True,
            allow_derived_crop=True,
            allow_report_embed=True,
            reason="open license with everywhere access",
        )

    # Library-only access is restrictive regardless of viewability:
    # accessAllowedFrom=LIBRARY requires library authentication the system
    # does not have, and viewability describes viewing inside that context,
    # not open reuse. Checked BEFORE the viewability branch so restricted
    # metadata is never upgraded to page-fetch rights (fail closed).
    if access_token in _LIBRARY_TOKENS:
        return NBAccessDecision(
            state=NBAccessState.LIBRARY_ONLY,
            upstream=upstream,
            allow_metadata=True,
            allow_context=True,
            allow_full_text_storage=False,
            allow_page_fetch=False,
            allow_derived_crop=False,
            allow_report_embed=False,
            reason="library-only access: metadata and short context only",
        )

    if access_token in _NB_ONLY_TOKENS:
        return NBAccessDecision(
            state=NBAccessState.NB_ONLY,
            upstream=upstream,
            allow_metadata=True,
            allow_context=True,
            allow_full_text_storage=False,
            allow_page_fetch=False,
            allow_derived_crop=False,
            allow_report_embed=False,
            reason="NB-only access: metadata and short context only",
        )

    # Viewable everywhere (or explicitly public) without reuse proof:
    # view-only. viewability=ALL alone NEVER grants embed rights.
    if viewability_token == "ALL" or access_token in _EVERYWHERE_TOKENS:
        return NBAccessDecision(
            state=NBAccessState.PUBLIC_VIEW_ONLY,
            upstream=upstream,
            allow_metadata=True,
            allow_context=True,
            allow_full_text_storage=False,
            allow_page_fetch=True,
            allow_derived_crop=True,
            allow_report_embed=False,
            reason="viewable but reuse not proven: viewability alone grants no embed rights",
        )

    return NBAccessDecision(
        state=NBAccessState.UNKNOWN,
        upstream=upstream,
        allow_metadata=True,
        allow_context=False,
        allow_full_text_storage=False,
        allow_page_fetch=False,
        allow_derived_crop=False,
        allow_report_embed=False,
        reason="unrecognized rights combination: fail closed",
    )


def decide_item_access(candidate: Any) -> NBAccessDecision:
    """Per-item decision from an executor-style issue candidate.

    The executor passes whole issue candidates (dict or attribute object with
    an ``access`` metadata field); the canonical normalization expects the
    bare access metadata dict. This adapter extracts the access fields and
    returns the canonical :class:`NBAccessDecision`.
    """
    if isinstance(candidate, dict):
        access = candidate.get("access", {}) or {}
    else:
        access = getattr(candidate, "access", {}) or {}
    if not isinstance(access, dict):
        access = {}
    return decide_access(access)


def _as_policy_dict(decision: NBAccessDecision) -> dict[str, Any]:
    """Map a canonical decision to the executor verdict field names."""
    return {
        "access_class": decision.state.value,
        "license_code": decision.upstream.get("license") or decision.upstream.get("licenseCode"),
        "allow_metadata": decision.allow_metadata,
        "allow_context": decision.allow_context,
        "allow_full_text_storage": decision.allow_full_text_storage,
        "allow_page_fetch": decision.allow_page_fetch,
        "allow_derived_crop": decision.allow_derived_crop,
        "allow_report_embed": decision.allow_report_embed,
        "reason": decision.reason,
    }


def ensure_page_fetch_permitted(decision: NBAccessDecision) -> None:
    """Rights gate for page/image downloading.

    Call this before any page-image downloader. Restricted decisions raise
    :class:`NBAccessDenied` so the downloader is never invoked.
    """
    if not decision.allow_page_fetch:
        raise NBAccessDenied(
            f"page fetch denied for access state {decision.state.value}: {decision.reason}",
            state=decision.state,
        )


def ensure_report_embed_permitted(decision: NBAccessDecision) -> None:
    """Rights gate for embedding page/crop images in reports."""
    if not decision.allow_report_embed:
        raise NBAccessDenied(
            f"report embed denied for access state {decision.state.value}: {decision.reason}",
            state=decision.state,
        )
