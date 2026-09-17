import pytest

from apps.api.app.domain.scope import ExpansionPolicy, ExpansionState, ScopeModule, ScopeSettings
from apps.api.app.services.scope_gate import check_research_scope


def _scope(*modules: ScopeModule, policy=ExpansionPolicy.DIRECT_RELATIONS, depth=1):
    return ScopeSettings(
        scope_modules=list(modules), expansion_policy=policy, max_relation_depth=depth
    )


def test_disabled_module_is_rejected_before_other_checks() -> None:
    decision = check_research_scope(
        _scope(),
        module=ScopeModule.BUSINESS_ROLES,
        information_need="company roles",
        expansion_state=ExpansionState.TARGET,
        relation_depth=0,
    )
    assert decision.allowed is False
    assert decision.reason == "module_disabled"


def test_target_is_allowed_at_depth_zero() -> None:
    decision = check_research_scope(
        _scope(ScopeModule.WEB_MEDIA),
        module=ScopeModule.WEB_MEDIA,
        information_need="verify target",
        expansion_state=ExpansionState.TARGET,
        relation_depth=0,
    )
    assert decision.allowed is True


def test_context_only_entity_cannot_expand() -> None:
    decision = check_research_scope(
        _scope(ScopeModule.COMPANY_NETWORK),
        module=ScopeModule.COMPANY_NETWORK,
        information_need="map relation",
        expansion_state=ExpansionState.CONTEXT_ONLY,
        relation_depth=1,
        verified_relation=True,
    )
    assert decision.reason == "entity_not_authorized"


def test_direct_relations_require_verified_depth_one() -> None:
    scope = _scope(ScopeModule.COMPANY_NETWORK)
    for depth in (0, 2):
        decision = check_research_scope(
            scope,
            module=ScopeModule.COMPANY_NETWORK,
            information_need="map relation",
            expansion_state=ExpansionState.RESEARCHED,
            relation_depth=depth,
            verified_relation=True,
        )
        assert decision.allowed is False
    allowed = check_research_scope(
        scope,
        module=ScopeModule.COMPANY_NETWORK,
        information_need="map relation",
        expansion_state=ExpansionState.RESEARCHED,
        relation_depth=1,
        verified_relation=True,
    )
    assert allowed.allowed is True


def test_material_policy_requires_material_reason() -> None:
    scope = _scope(
        ScopeModule.FINANCIALS,
        policy=ExpansionPolicy.MATERIAL_RELATIONS,
        depth=2,
    )
    missing = check_research_scope(
        scope,
        module=ScopeModule.FINANCIALS,
        information_need="review accounts",
        expansion_state=ExpansionState.MATERIAL,
        relation_depth=1,
        verified_relation=True,
    )
    assert missing.reason == "material_reason_required"
    accepted = check_research_scope(
        scope,
        module=ScopeModule.FINANCIALS,
        information_need="review accounts",
        expansion_state=ExpansionState.MATERIAL,
        relation_depth=1,
        verified_relation=True,
        material_reason="material subsidiary for target company",
    )
    assert accepted.allowed is True


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"information_need": "  "}, "information_need_required"),
        ({"source_enabled": False}, "source_or_policy_blocked"),
        ({"policy_allowed": False}, "source_or_policy_blocked"),
        ({"budget_available": False}, "budget_exhausted"),
        ({"relation_depth": 2}, "relation_depth_exceeded"),
    ],
)
def test_deterministic_gate_blocks_invalid_context(kwargs, reason) -> None:
    base = {
        "module": ScopeModule.BUSINESS_ROLES,
        "information_need": "find roles",
        "expansion_state": ExpansionState.TARGET,
        "relation_depth": 0,
    }
    base.update(kwargs)
    decision = check_research_scope(_scope(ScopeModule.BUSINESS_ROLES), **base)
    assert decision.allowed is False
    assert decision.reason == reason


def test_financials_on_non_material_relation_is_blocked() -> None:
    decision = check_research_scope(
        _scope(ScopeModule.FINANCIALS),
        module=ScopeModule.FINANCIALS,
        information_need="review accounts",
        expansion_state=ExpansionState.RESEARCHED,
        relation_depth=1,
        verified_relation=True,
    )
    assert decision.reason == "financial_materiality_required"
