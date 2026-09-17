"""Search-trigger eval suite (AQ-007).

Locks the trigger-driven research contract end to end: company/person
auto-expansion without active scope must be caught, contradiction leads stay
targeted, repeated loops stop, and no-unnecessary-expansion holds. The suite
exercises the deterministic gate layer only; no model calls.
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
from apps.api.app.services.scope_gate import check_research_scope


def _scope(*modules: ScopeModule, policy=ExpansionPolicy.DIRECT_RELATIONS, depth=1):
    return ScopeSettings(
        scope_modules=list(modules),
        expansion_policy=ExpansionPolicy(policy),
        max_relation_depth=depth,
    )


def _lead(
    module: ScopeModule = ScopeModule.COMPANY_NETWORK,
    trigger: TriggerType = TriggerType.MATERIAL_RELATION,
    relation_depth: int = 1,
    information_need: str = "Documented relation between target and related entity",
    value: dict | None = None,
    **overrides,
):
    payload = {
        "lead_type": "relation_lookup",
        "value": value or {"entity": "Subsidiary AS"},
        "reason": "Documented board role connects the target to this entity",
        "priority": 0.5,
        "depth": relation_depth,
        "originating_claim_id": uuid4(),
        "scope_area": module,
        "trigger_type": trigger,
        "information_need": information_need,
        "relation_depth": relation_depth,
    }
    payload.update(overrides)
    return Lead(**payload)


# --- Acceptance: company/person auto-expansion without active scope is caught


@pytest.mark.parametrize(
    ("module", "trigger"),
    [
        (ScopeModule.COMPANY_NETWORK, TriggerType.MATERIAL_RELATION),
        (ScopeModule.WEB_MEDIA, TriggerType.TEMPORAL_GAP),
        (ScopeModule.BUSINESS_ROLES, TriggerType.FINANCIAL_ANOMALY),
        (ScopeModule.SANCTIONS, TriggerType.SANCTIONS_CANDIDATE),
    ],
)
def test_auto_expansion_without_scope_is_blocked(module, trigger) -> None:
    decision = check_research_scope(
        _scope(),
        module=module,
        information_need="Follow the discovered relation",
        expansion_state=ExpansionState.RESEARCHED,
        relation_depth=1,
        verified_relation=True,
    )
    assert decision.allowed is False
    assert decision.reason == "module_disabled"


def test_discovered_company_lead_cannot_ride_on_web_media_scope() -> None:
    reason = gate_lead(
        _scope(ScopeModule.WEB_MEDIA),
        _lead(module=ScopeModule.COMPANY_NETWORK, trigger=TriggerType.MATERIAL_RELATION),
        expansion_state=ExpansionState.RESEARCHED,
        verified_relation=True,
    )
    assert reason == "module_disabled"


def test_person_context_only_cannot_auto_expand_to_relations() -> None:
    reason = gate_lead(
        _scope(ScopeModule.COMPANY_NETWORK, policy="CONTEXT_ONLY", depth=0),
        _lead(trigger=TriggerType.MATERIAL_RELATION),
        expansion_state=ExpansionState.RESEARCHED,
        verified_relation=True,
    )
    assert reason == "context_only_policy"


def test_passive_sanctions_match_cannot_auto_execute() -> None:
    reason = gate_lead(
        _scope(ScopeModule.SANCTIONS),
        _lead(
            module=ScopeModule.SANCTIONS,
            trigger=TriggerType.SANCTIONS_CANDIDATE,
            value={"name": "Ola Nordmann"},
            reason="Fuzzy name match against sanctions list",
        ),
        expansion_state=ExpansionState.RESEARCHED,
        verified_relation=True,
    )
    assert reason == "passive_trigger_requires_review"


# --- Trigger routing: targeted response per trigger class


def test_contradiction_lead_is_targeted_not_broad() -> None:
    reason = gate_lead(
        _scope(ScopeModule.WEB_MEDIA),
        _lead(
            module=ScopeModule.WEB_MEDIA,
            trigger=TriggerType.CONTRADICTION,
            relation_depth=0,
            information_need="Disconfirm the conflicting registered status claim",
        ),
        expansion_state=ExpansionState.TARGET,
    )
    assert reason is None


def test_financial_anomaly_requires_financials_scope_and_materiality() -> None:
    lead = _lead(
        module=ScopeModule.FINANCIALS,
        trigger=TriggerType.FINANCIAL_ANOMALY,
        information_need="Explain revenue anomaly across fiscal years",
    )
    assert (
        gate_lead(
            _scope(ScopeModule.WEB_MEDIA),
            lead,
            expansion_state=ExpansionState.MATERIAL,
            verified_relation=True,
            material_reason="Subsidiary of the target",
        )
        == "module_disabled"
    )
    assert (
        gate_lead(
            _scope(ScopeModule.FINANCIALS, depth=2),
            lead,
            expansion_state=ExpansionState.RESEARCHED,
            verified_relation=True,
        )
        == "financial_materiality_required"
    )
    assert (
        gate_lead(
            _scope(ScopeModule.FINANCIALS, policy="MATERIAL_RELATIONS", depth=2),
            lead,
            expansion_state=ExpansionState.MATERIAL,
            verified_relation=True,
            material_reason="Target is daily manager of this subsidiary",
        )
        is None
    )


def test_temporal_gap_routes_to_historical_module_only_when_selected() -> None:
    lead = _lead(
        module=ScopeModule.HISTORICAL_WEB,
        trigger=TriggerType.TEMPORAL_GAP,
        information_need="Timeline between role change and registry update",
    )
    assert (
        gate_lead(
            _scope(ScopeModule.WEB_MEDIA),
            lead,
            expansion_state=ExpansionState.TARGET,
        )
        == "module_disabled"
    )
    assert (
        gate_lead(
            _scope(ScopeModule.HISTORICAL_WEB, depth=1),
            lead,
            expansion_state=ExpansionState.TARGET,
        )
        == "invalid_target"
    )
    # The same temporal-gap lead on a verified relation is schedulable.
    assert (
        gate_lead(
            _scope(ScopeModule.HISTORICAL_WEB, depth=1),
            lead,
            expansion_state=ExpansionState.RESEARCHED,
            verified_relation=True,
        )
        is None
    )


# --- No-loop and budget stops


def test_budget_exhaustion_stops_the_lead() -> None:
    assert (
        gate_lead(
            _scope(ScopeModule.WEB_MEDIA),
            _lead(
                module=ScopeModule.WEB_MEDIA,
                trigger=TriggerType.CONTRADICTION,
                relation_depth=0,
            ),
            expansion_state=ExpansionState.TARGET,
            budget_available=False,
        )
        == "budget_exhausted"
    )


def test_disabled_source_stops_the_lead() -> None:
    assert (
        gate_lead(
            _scope(ScopeModule.WEB_MEDIA),
            _lead(
                module=ScopeModule.WEB_MEDIA,
                trigger=TriggerType.CONTRADICTION,
                relation_depth=0,
            ),
            expansion_state=ExpansionState.TARGET,
            source_enabled=False,
        )
        == "source_or_policy_blocked"
    )


def test_relation_loop_beyond_depth_limit_is_blocked() -> None:
    # A chain of leads each one step deeper must stop at max_relation_depth.
    scope = _scope(ScopeModule.COMPANY_NETWORK, depth=1)
    for depth in (1, 2, 3):
        reason = gate_lead(
            scope,
            _lead(relation_depth=depth),
            expansion_state=ExpansionState.RESEARCHED,
            verified_relation=True,
        )
        if depth > 1:
            assert reason == "relation_depth_exceeded"
        else:
            assert reason is None


def test_unverified_relation_chain_cannot_repeat_expansion() -> None:
    # Every repeated expansion hop must again prove a verified relation.
    for _hop in range(3):
        assert (
            gate_lead(
                _scope(ScopeModule.COMPANY_NETWORK, depth=3),
                _lead(relation_depth=1),
                expansion_state=ExpansionState.RESEARCHED,
                verified_relation=False,
            )
            == "verified_relation_required"
        )
