"""Deterministic scope checks at the tool-execution boundary."""

from apps.api.app.domain.scope import (
    ExpansionPolicy,
    ExpansionState,
    ScopeModule,
    ScopeSettings,
)
from apps.api.app.services.policy import PolicyDecision


def check_research_scope(
    scope: ScopeSettings,
    *,
    module: ScopeModule,
    information_need: str,
    expansion_state: ExpansionState,
    relation_depth: int,
    verified_relation: bool = False,
    material_reason: str | None = None,
    source_enabled: bool = True,
    policy_allowed: bool = True,
    budget_available: bool = True,
) -> PolicyDecision:
    if module not in scope.scope_modules:
        return PolicyDecision(False, "module_disabled")
    if not information_need.strip():
        return PolicyDecision(False, "information_need_required")
    if not source_enabled or not policy_allowed:
        return PolicyDecision(False, "source_or_policy_blocked")
    if not budget_available:
        return PolicyDecision(False, "budget_exhausted")
    if relation_depth < 0 or relation_depth > scope.max_relation_depth:
        return PolicyDecision(False, "relation_depth_exceeded")
    if expansion_state == ExpansionState.TARGET:
        return PolicyDecision(
            relation_depth == 0, "target" if relation_depth == 0 else "invalid_target"
        )
    if expansion_state in (ExpansionState.CONTEXT_ONLY, ExpansionState.BLOCKED):
        return PolicyDecision(False, "entity_not_authorized")
    if scope.expansion_policy == ExpansionPolicy.CONTEXT_ONLY:
        return PolicyDecision(False, "context_only_policy")
    if not verified_relation or relation_depth == 0:
        return PolicyDecision(False, "verified_relation_required")
    if scope.expansion_policy == ExpansionPolicy.DIRECT_RELATIONS and relation_depth != 1:
        return PolicyDecision(False, "direct_relation_required")
    if scope.expansion_policy == ExpansionPolicy.MATERIAL_RELATIONS and not (
        expansion_state == ExpansionState.MATERIAL and material_reason and material_reason.strip()
    ):
        return PolicyDecision(False, "material_reason_required")
    if module == ScopeModule.FINANCIALS and expansion_state != ExpansionState.MATERIAL:
        return PolicyDecision(False, "financial_materiality_required")
    return PolicyDecision(True, "within_scope")
