"""Dynamic report sections per module outcome (AQ-006).

The report separates investigated, investigated-with-gaps, not investigated,
unavailable and not selected. A disabled module is never a negative finding.
"""


from apps.api.app.domain.scope import (
    Coverage,
    InvestigationModuleRecord,
    ModuleStatus,
    ScopeModule,
    ScopeSettings,
)
from apps.api.app.services.report_sections import report_sections


def _record(
    module=ScopeModule.WEB_MEDIA,
    enabled=True,
    status=ModuleStatus.COMPLETE,
    stop_reason=None,
    coverage=None,
):
    return InvestigationModuleRecord(
        module=module,
        enabled=enabled,
        status=status,
        stop_reason=stop_reason,
        coverage=coverage or Coverage(),
    )


def _scope(*modules):
    return ScopeSettings(scope_modules=list(modules))


def test_disabled_module_is_not_selected_never_negative_finding() -> None:
    sections = report_sections(_scope(), [_record(enabled=False)])
    assert [item["module"] for item in sections["Ikke valgt"]] == ["WEB_MEDIA"]
    assert sections["Undersøkt"] == []
    assert sections["Ikke undersøkt"] == []


def test_not_started_enabled_module_is_not_investigated() -> None:
    sections = report_sections(
        _scope(ScopeModule.WEB_MEDIA),
        [_record(status=ModuleStatus.NOT_STARTED)],
    )
    assert [item["module"] for item in sections["Ikke undersøkt"]] == ["WEB_MEDIA"]


def test_complete_module_is_investigated_with_coverage() -> None:
    coverage = Coverage(
        providers=["brreg_entities"],
        query_count=3,
        document_count=2,
    )
    sections = report_sections(
        _scope(ScopeModule.BUSINESS_ROLES),
        [_record(module=ScopeModule.BUSINESS_ROLES, coverage=coverage)],
    )
    entry = sections["Undersøkt"][0]
    assert entry["module"] == "BUSINESS_ROLES"
    assert entry["coverage"]["providers"] == ["brreg_entities"]
    assert entry["coverage"]["query_count"] == 3
    assert entry["stop_reason"] is None


def test_stop_reason_yields_incomplete_section() -> None:
    sections = report_sections(
        _scope(ScopeModule.WEB_MEDIA),
        [_record(status=ModuleStatus.PARTIAL, stop_reason="budget_exhausted")],
    )
    assert sections["Undersøkt med mangler"][0]["stop_reason"] == "budget_exhausted"


def test_unavailable_stop_reason_is_separate_from_incomplete() -> None:
    sections = report_sections(
        _scope(ScopeModule.HISTORICAL_WEB),
        [
            _record(
                module=ScopeModule.HISTORICAL_WEB,
                status=ModuleStatus.BLOCKED,
                stop_reason="unavailable_upstream",
            )
        ],
    )
    assert sections["Utilgjengelig"][0]["module"] == "HISTORICAL_WEB"
    assert sections["Undersøkt med mangler"] == []


def test_blocked_without_stop_reason_is_unavailable() -> None:
    sections = report_sections(
        _scope(ScopeModule.SANCTIONS),
        [
            _record(
                module=ScopeModule.SANCTIONS,
                status=ModuleStatus.BLOCKED,
            )
        ],
    )
    assert sections["Utilgjengelig"][0]["module"] == "SANCTIONS"


def test_mixed_scopes_landed_in_separate_sections() -> None:
    sections = report_sections(
        _scope(ScopeModule.WEB_MEDIA, ScopeModule.BUSINESS_ROLES, ScopeModule.SANCTIONS),
        [
            _record(module=ScopeModule.WEB_MEDIA),
            _record(
                module=ScopeModule.BUSINESS_ROLES,
                status=ModuleStatus.PARTIAL,
                stop_reason="source_rate_limited",
            ),
            _record(module=ScopeModule.SANCTIONS, enabled=False),
        ],
    )
    assert [item["module"] for item in sections["Undersøkt"]] == ["WEB_MEDIA"]
    assert [item["module"] for item in sections["Undersøkt med mangler"]] == [
        "BUSINESS_ROLES"
    ]
    assert [item["module"] for item in sections["Ikke valgt"]] == ["SANCTIONS"]
    assert sections["Ikke undersøkt"] == []
    assert sections["Utilgjengelig"] == []
