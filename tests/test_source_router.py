import pytest

from apps.api.app.services.source_router import (
    EXECUTOR_ROUTES,
    UnknownLeadType,
    route_lead,
    supported_lead_types,
)


def test_all_four_types_route_correctly() -> None:
    assert route_lead("brreg_organization_lookup") == "brreg"
    assert route_lead("searxng_discovery") == "searxng"
    assert route_lead("web_document_fetch") == "web_fetch"
    assert route_lead("pdf_document_process") == "pdf"


def test_unknown_raises() -> None:
    with pytest.raises(UnknownLeadType):
        route_lead("no_such_lead")


def test_empty_raises() -> None:
    with pytest.raises(UnknownLeadType):
        route_lead("")


def test_wrong_case_raises() -> None:
    with pytest.raises(UnknownLeadType):
        route_lead("BRREG_ORGANIZATION_LOOKUP")
    with pytest.raises(UnknownLeadType):
        route_lead("Searxng_Discovery")


def test_mapping_values_unique() -> None:
    values = list(EXECUTOR_ROUTES.values())
    assert len(values) == len(set(values))


def test_keys_non_empty() -> None:
    assert len(EXECUTOR_ROUTES) > 0
    for key in EXECUTOR_ROUTES:
        assert isinstance(key, str) and key != ""


def test_supported_lead_types_matches_keys() -> None:
    assert supported_lead_types() == frozenset(EXECUTOR_ROUTES.keys())
