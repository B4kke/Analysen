"""Admission rules for proposed leads (AQ-005).

Discovery and model output may propose leads, but only the deterministic gate
decides whether a lead can be scheduled. These tests lock the contract that
discovery alone cannot authorize expansion.
"""

from uuid import uuid4

import pytest

from apps.api.app.domain.models import Lead
from apps.api.app.domain.scope import (
    ExpansionPolicy,
    ExpansionState,
    ScopeModule,
    ScopeSettings,
    TriggerType,
)
from apps.api.app.services.lead_gate import gate_lead


def _scope(*modules: ScopeModule, policy="DIRECT_RELATIONS", depth=1):

    return ScopeSettings(
        scope_modules=list(modules),
        expansion_policy=ExpansionPolicy(policy),
        max_relation_depth=depth,
    )


def _lead(
    module: ScopeModule = ScopeModule.WEB_MEDIA,
    trigger: TriggerType = TriggerType.MEDIA_CORROBORATION,
    relation_depth: int = 1,
    information_need: str = "Independent confirmation of registered address",
    **overrides,
):
    payload = {
        "lead_type": "web_media_lookup",
        "value": {"url": "https://example.com/article"},
        "reason": "Verifies registered status from an independent secondary source",
        "priority": 0.5,
        "depth": 1,
        "originating_claim_id": uuid4(),
        "scope_area": module,
        "trigger_type": trigger,
        "information_need": information_need,
        "relation_depth": relation_depth,
    }
    payload.update(overrides)
    return Lead(**payload)


@pytest.mark.parametrize(
    "trigger",
    [
        TriggerType.NEW_VERIFIED_ALIAS,
        TriggerType.MEDIA_CORROBORATION,
        TriggerType.SANCTIONS_CANDIDATE,
    ],
)
def test_passive_discovery_triggers_are_never_self_executable(trigger) -> None:
    reason = gate_lead(
        _scope(ScopeModule.WEB_MEDIA),
        _lead(trigger=trigger),
        expansion_state=ExpansionState.RESEARCHED,
        verified_relation=True,
    )
    assert reason == "passive_trigger_requires_review"


def test_passive_trigger_on_target_is_schedulable() -> None:
    reason = gate_lead(
        _scope(ScopeModule.WEB_MEDIA),
        _lead(trigger=TriggerType.NEW_VERIFIED_ALIAS, relation_depth=0),
        expansion_state=ExpansionState.TARGET,
    )
    assert reason is None


def test_disabled_module_blocks_lead_before_other_checks() -> None:
    assert (
        gate_lead(
            _scope(),
            _lead(module=ScopeModule.BUSINESS_ROLES, trigger=TriggerType.MATERIAL_RELATION),
            expansion_state=ExpansionState.RESEARCHED,
            verified_relation=True,
        )
        == "module_disabled"
    )


def test_context_only_policy_blocks_relation_leads() -> None:
    assert (
        gate_lead(
            _scope(ScopeModule.COMPANY_NETWORK, policy="CONTEXT_ONLY", depth=0),
            _lead(
                module=ScopeModule.COMPANY_NETWORK,
                trigger=TriggerType.MATERIAL_RELATION,
            ),
            expansion_state=ExpansionState.RESEARCHED,
            verified_relation=True,
        )
        == "context_only_policy"
    )


def test_context_only_policy_allows_target_leads() -> None:
    reason = gate_lead(
        _scope(ScopeModule.WEB_MEDIA, policy="CONTEXT_ONLY", depth=0),
        _lead(relation_depth=0, trigger=TriggerType.WEAK_SOURCE_ONLY),
        expansion_state=ExpansionState.TARGET,
    )
    assert reason is None


def test_unverified_relation_cannot_authorize_expansion() -> None:
    assert (
        gate_lead(
            _scope(ScopeModule.COMPANY_NETWORK),
            _lead(
                module=ScopeModule.COMPANY_NETWORK,
                trigger=TriggerType.MATERIAL_RELATION,
            ),
            expansion_state=ExpansionState.RESEARCHED,
            verified_relation=False,
        )
        == "verified_relation_required"
    )


def test_depth_is_enforced_for_relation_leads() -> None:
    assert (
        gate_lead(
            _scope(ScopeModule.COMPANY_NETWORK, depth=1),
            _lead(
                module=ScopeModule.COMPANY_NETWORK,
                trigger=TriggerType.MATERIAL_RELATION,
                relation_depth=2,
            ),
            expansion_state=ExpansionState.RESEARCHED,
            verified_relation=True,
        )
        == "relation_depth_exceeded"
    )


def test_material_policy_requires_documented_reason() -> None:
    lead = _lead(
        module=ScopeModule.FINANCIALS,
        trigger=TriggerType.FINANCIAL_ANOMALY,
        information_need="Explain year-over-year revenue anomaly",
    )
    scope = _scope(ScopeModule.FINANCIALS, policy="MATERIAL_RELATIONS", depth=2)
    assert (
        gate_lead(
            scope,
            lead,
            expansion_state=ExpansionState.MATERIAL,
            verified_relation=True,
        )
        == "material_reason_required"
    )
    assert (
        gate_lead(
            scope,
            lead,
            expansion_state=ExpansionState.MATERIAL,
            verified_relation=True,
            material_reason="Target is documented daily manager of the subsidiary",
        )
        is None
    )


def test_budget_and_source_blocks_are_deterministic() -> None:
    lead = _lead(trigger=TriggerType.WEAK_SOURCE_ONLY)
    scope = _scope(ScopeModule.WEB_MEDIA)
    assert (
        gate_lead(scope, lead, expansion_state=ExpansionState.TARGET, source_enabled=False)
        == "source_or_policy_blocked"
    )
    assert (
        gate_lead(scope, lead, expansion_state=ExpansionState.TARGET, budget_available=False)
        == "budget_exhausted"
    )


def test_empty_information_need_is_rejected() -> None:
    with pytest.raises(ValueError):
        _lead(information_need="  ")
