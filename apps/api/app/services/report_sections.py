"""Dynamic report state per scope module (AQ-006).

The report must separate what was investigated, what was investigated with
gaps, what was never investigated (by choice or by stop), and what was
unavailable. Absence of findings in a disabled module is never a negative
finding; it is reported as not selected.
"""

from collections.abc import Sequence

from apps.api.app.domain.scope import (
    InvestigationModuleRecord,
    ModuleStatus,
    ScopeSettings,
)

# Human-readable section headings per outcome, no hidden policy here.
_NOT_SELECTED = "Ikke valgt"
_NOT_INVESTIGATED = "Ikke undersøkt"
_INCOMPLETE = "Undersøkt med mangler"
_UNAVAILABLE = "Utilgjengelig"
_INVESTIGATED = "Undersøkt"


def _outcome(record: InvestigationModuleRecord) -> str:
    if not record.enabled:
        return _NOT_SELECTED
    if record.stop_reason:
        if record.stop_reason.startswith("unavailable"):
            return _UNAVAILABLE
        return _INCOMPLETE
    if record.status == ModuleStatus.COMPLETE:
        return _INVESTIGATED
    if record.status == ModuleStatus.BLOCKED:
        return _UNAVAILABLE
    if record.status == ModuleStatus.PARTIAL:
        return _INCOMPLETE
    return _NOT_INVESTIGATED


def _entry(record: InvestigationModuleRecord) -> dict:
    return {
        "module": record.module.value,
        "status": record.status.value,
        "stop_reason": record.stop_reason,
        "coverage": record.coverage.model_dump(mode="json"),
    }


def report_sections(
    scope: ScopeSettings, modules: Sequence[InvestigationModuleRecord]
) -> dict[str, list[dict]]:
    """Group module records into dynamic report sections.

    Disabled modules are listed as not selected and are never presented as
    negative findings. Enabled modules get their coverage summary so the
    report can describe the actual search effort.
    """
    sections: dict[str, list[dict]] = {
        _INVESTIGATED: [],
        _INCOMPLETE: [],
        _NOT_INVESTIGATED: [],
        _UNAVAILABLE: [],
        _NOT_SELECTED: [],
    }
    for module in modules:
        sections[_outcome(module)].append(_entry(module))
    return sections
