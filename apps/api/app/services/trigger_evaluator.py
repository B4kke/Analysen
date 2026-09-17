"""Deterministic trigger evaluator (AQ-012).

Maps a proposed lead and its evidence state to one typed decision. Discovery
alone can never produce FOLLOW_UP_LEAD: passive triggers become CONTEXT_ONLY
and unverified relations become CONTEXT_ONLY until a verified relation exists.
No model calls; the planner may suggest, but this function disposes.
"""

from apps.api.app.domain.models import Lead
from apps.api.app.domain.scope import (
    ExpansionPolicy,
    ExpansionState,
    ScopeModule,
    ScopeSettings,
    TriggerType,
)
from apps.api.app.domain.trigger_eval import TriggerDecision, TriggerEvaluation

# Discovery-derived triggers never authorize follow-up research on their own.
_PASSIVE_TRIGGERS = frozenset(
    {
        TriggerType.NEW_VERIFIED_ALIAS,
        TriggerType.MEDIA_CORROBORATION,
        TriggerType.SANCTIONS_CANDIDATE,
    }
)


def evaluate_trigger(
    scope: ScopeSettings,
    lead: Lead,
    *,
    expansion_state: ExpansionState = ExpansionState.TARGET,
    verified_relation: bool = False,
    material_reason: str | None = None,
    budget_available: bool = True,
    information_need_answered: bool = False,
    question_already_exhausted: bool = False,
) -> TriggerEvaluation:
    """Evaluate one lead proposal into a typed routing decision."""
    if lead.scope_area not in scope.scope_modules:
        return TriggerEvaluation(
            decision=TriggerDecision.BLOCKED_BY_SCOPE,
            reason="module_disabled",
        )
    if not budget_available:
        return TriggerEvaluation(
            decision=TriggerDecision.STOP_BUDGET,
            reason="budget_exhausted",
        )
    if information_need_answered:
        return TriggerEvaluation(
            decision=TriggerDecision.STOP_SUFFICIENT,
            reason="information_need_answered",
        )
    if question_already_exhausted:
        return TriggerEvaluation(
            decision=TriggerDecision.STOP_LOW_VALUE,
            reason="question_already_exhausted",
        )
    if lead.trigger_type in _PASSIVE_TRIGGERS:
        return TriggerEvaluation(
            decision=TriggerDecision.CONTEXT_ONLY,
            reason="passive_trigger_requires_review",
        )
    if lead.trigger_type == TriggerType.CONTRADICTION:
        # A contradiction gets a targeted disconfirmation lead on the same
        # entity — never a new broad search.
        if expansion_state == ExpansionState.TARGET and lead.relation_depth == 0:
            return TriggerEvaluation(
                decision=TriggerDecision.VERIFICATION_LEAD,
                reason="targeted_disconfirmation",
            )
        return TriggerEvaluation(
            decision=TriggerDecision.CONTEXT_ONLY,
            reason="contradiction_off_target_requires_review",
        )
    if lead.trigger_type == TriggerType.FINANCIAL_ANOMALY:
        if lead.scope_area != ScopeModule.FINANCIALS:
            return TriggerEvaluation(
                decision=TriggerDecision.BLOCKED_BY_SCOPE,
                reason="financials_module_required",
            )
        if not (
            expansion_state == ExpansionState.MATERIAL
            and material_reason
            and material_reason.strip()
        ):
            return TriggerEvaluation(
                decision=TriggerDecision.CONTEXT_ONLY,
                reason="financial_materiality_required",
            )
        return TriggerEvaluation(
            decision=TriggerDecision.FOLLOW_UP_LEAD,
            reason="material_financial_anomaly",
        )
    if lead.trigger_type == TriggerType.MATERIAL_RELATION:
        if not verified_relation:
            return TriggerEvaluation(
                decision=TriggerDecision.CONTEXT_ONLY,
                reason="verified_relation_required",
            )
        if scope.expansion_policy == ExpansionPolicy.CONTEXT_ONLY:
            return TriggerEvaluation(
                decision=TriggerDecision.CONTEXT_ONLY,
                reason="context_only_policy",
            )
        if lead.relation_depth > scope.max_relation_depth:
            return TriggerEvaluation(
                decision=TriggerDecision.STOP_LOW_VALUE,
                reason="relation_depth_exceeded",
            )
        return TriggerEvaluation(
            decision=TriggerDecision.FOLLOW_UP_LEAD,
            reason="verified_material_relation",
        )
    # Active investigative triggers on the target with remaining budget.
    if expansion_state == ExpansionState.TARGET and lead.relation_depth == 0:
        return TriggerEvaluation(
            decision=TriggerDecision.FOLLOW_UP_LEAD,
            reason="target_information_need",
        )
    if verified_relation and lead.relation_depth <= scope.max_relation_depth:
        return TriggerEvaluation(
            decision=TriggerDecision.FOLLOW_UP_LEAD,
            reason="verified_relation_follow_up",
        )
    return TriggerEvaluation(
        decision=TriggerDecision.CONTEXT_ONLY,
        reason="unverified_expansion_requires_review",
    )
