from apps.api.app.domain.models import BrregOrganization


def is_business_role_context(organization: BrregOrganization) -> bool:
    """Return whether a role may appear in a combined person/business overview.

    BRREG describes the relevant population as entities registered in the
    Register of Business Enterprises plus all sole proprietorships (ENK).
    """

    return bool(
        organization.status_flags.get("registered_in_business_register")
        or organization.organization_form_code == "ENK"
    )
