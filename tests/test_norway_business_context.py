from apps.api.app.domain.models import BrregOrganization
from apps.api.app.services.norway_business_context import is_business_role_context


def test_business_register_entity_is_allowed() -> None:
    organization = BrregOrganization(
        organization_number="974760673",
        name="EKSEMPEL AS",
        organization_form_code="AS",
        status_flags={"registered_in_business_register": True},
    )
    assert is_business_role_context(organization)


def test_sole_proprietorship_is_allowed_without_business_flag() -> None:
    organization = BrregOrganization(
        organization_number="974760673",
        name="EKSEMPEL ENK",
        organization_form_code="ENK",
        status_flags={"registered_in_business_register": False},
    )
    assert is_business_role_context(organization)


def test_voluntary_only_entity_is_not_allowed() -> None:
    organization = BrregOrganization(
        organization_number="974760673",
        name="EKSEMPEL FORENING",
        organization_form_code="FLI",
        status_flags={
            "registered_in_business_register": False,
            "registered_in_voluntary_register": True,
        },
    )
    assert not is_business_role_context(organization)
