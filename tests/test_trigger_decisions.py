"""Trigger evaluator and frontier selection contract (AQ-012).

Discovery alone must never authorize expansion: passive triggers and
unverified relations become CONTEXT_ONLY. Contradictions get targeted
verification, never broad search. Stops are explicit and typed.
"""

from uuid import uuid4

from apps.api.app.domain.models import Lead
from apps.api.app.domain.scope import (
    ExpansionPolicy,
    ExpansionState,
    ScopeModule,
    ScopeSettings,
    TriggerType,
)
from apps.api.app.domain.trigger_eval import FrontierLead, TriggerDecision
from apps.api.app.services.frontier import select_next
from apps.api.app.services.trigger_evaluator import evaluate_trigger


def _scope(*modules: ScopeModule, policy="DIRECT_RELATIONS", depth=1):
    return ScopeSettings(
        scope_modules=list(modules),
        expansion_policy=ExpansionPolicy(policy),
        max_relation_depth=depth,
    )


def _lead(
    module: ScopeModule = ScopeModule.WEB_MEDIA,
    trigger: TriggerType = TriggerType.CONTRADICTION,
    relation_depth: int = 0,
    information_need: str = "Resolve the open question with primary evidence",
    **overrides,
):
    payload = {
        "lead_type": "target_lookup",
        "value": {"entity": "Target AS"},
        "reason": "Directly answers the open information need",
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


def _frontier_lead(status: str = "PENDING", priority: float = 0.5, depth: int = 0):
    payload = _lead().model_dump()
    payload.update({"status": status, "priority": priority, "depth": depth})
    return FrontierLead(**payload)


def test_out_of_scope_is_blocked() -> None:
    evaluation = evaluate_trigger(_scope(), _lead(module=ScopeModule.WEB_MEDIA))
    assert evaluation.decision == TriggerDecision.BLOCKED_BY_SCOPE


def test_passive_triggers_become_context_only() -> None:
    for trigger in (
        TriggerType.NEW_VERIFIED_ALIAS,
        TriggerType.MEDIA_CORROBORATION,
        TriggerType.SANCTIONS_CANDIDATE,
    ):
        evaluation = evaluate_trigger(
            _scope(ScopeModule.WEB_MEDIA),
            _lead(trigger=trigger),
            expansion_state=ExpansionState.RESEARCHED,
            verified_relation=True,
        )
        assert evaluation.decision == TriggerDecision.CONTEXT_ONLY


def test_contradiction_on_target_gets_verification_lead() -> None:
    evaluation = evaluate_trigger(
        _scope(ScopeModule.WEB_MEDIA),
        _lead(trigger=TriggerType.CONTRADICTION),
        expansion_state=ExpansionState.TARGET,
    )
    assert evaluation.decision == TriggerDecision.VERIFICATION_LEAD


def test_contradiction_off_target_needs_review() -> None:
    evaluation = evaluate_trigger(
        _scope(ScopeModule.WEB_MEDIA),
        _lead(trigger=TriggerType.CONTRADICTION, relation_depth=1),
        expansion_state=ExpansionState.RESEARCHED,
        verified_relation=True,
    )
    assert evaluation.decision == TriggerDecision.CONTEXT_ONLY


def test_unverified_relation_never_follows_up() -> None:
    for _hop in range(3):
        evaluation = evaluate_trigger(
            _scope(ScopeModule.COMPANY_NETWORK, depth=3),
            _lead(
                module=ScopeModule.COMPANY_NETWORK,
                trigger=TriggerType.MATERIAL_RELATION,
                relation_depth=1,
            ),
            expansion_state=ExpansionState.RESEARCHED,
            verified_relation=False,
        )
        assert evaluation.decision == TriggerDecision.CONTEXT_ONLY


def test_verified_relation_follows_up_within_policy() -> None:
    evaluation = evaluate_trigger(
        _scope(ScopeModule.COMPANY_NETWORK),
        _lead(
            module=ScopeModule.COMPANY_NETWORK,
            trigger=TriggerType.MATERIAL_RELATION,
            relation_depth=1,
        ),
        expansion_state=ExpansionState.RESEARCHED,
        verified_relation=True,
    )
    assert evaluation.decision == TriggerDecision.FOLLOW_UP_LEAD


def test_context_only_policy_keeps_relations_as_context() -> None:
    evaluation = evaluate_trigger(
        _scope(ScopeModule.COMPANY_NETWORK, policy="CONTEXT_ONLY", depth=0),
        _lead(
            module=ScopeModule.COMPANY_NETWORK,
            trigger=TriggerType.MATERIAL_RELATION,
            relation_depth=1,
        ),
        expansion_state=ExpansionState.RESEARCHED,
        verified_relation=True,
    )
    assert evaluation.decision == TriggerDecision.CONTEXT_ONLY


def test_financial_anomaly_requires_material_module() -> None:
    lead = _lead(
        module=ScopeModule.FINANCIALS,
        trigger=TriggerType.FINANCIAL_ANOMALY,
        information_need="Explain revenue anomaly",
    )
    assert (
        evaluate_trigger(_scope(ScopeModule.WEB_MEDIA), lead).decision
        == TriggerDecision.BLOCKED_BY_SCOPE
    )
    assert (
        evaluate_trigger(
            _scope(ScopeModule.FINANCIALS, depth=2),
            lead,
            expansion_state=ExpansionState.RESEARCHED,
            verified_relation=True,
        ).decision
        == TriggerDecision.CONTEXT_ONLY
    )
    assert (
        evaluate_trigger(
            _scope(ScopeModule.FINANCIALS, policy="MATERIAL_RELATIONS", depth=2),
            lead,
            expansion_state=ExpansionState.MATERIAL,
            verified_relation=True,
            material_reason="Target manages this subsidiary",
        ).decision
        == TriggerDecision.FOLLOW_UP_LEAD
    )


def test_answered_and_exhausted_questions_stop() -> None:
    lead = _lead()
    assert (
        evaluate_trigger(
            _scope(ScopeModule.WEB_MEDIA), lead, information_need_answered=True
        ).decision
        == TriggerDecision.STOP_SUFFICIENT
    )
    assert (
        evaluate_trigger(
            _scope(ScopeModule.WEB_MEDIA), lead, question_already_exhausted=True
        ).decision
        == TriggerDecision.STOP_LOW_VALUE
    )
    assert (
        evaluate_trigger(
            _scope(ScopeModule.WEB_MEDIA), lead, budget_available=False
        ).decision
        == TriggerDecision.STOP_BUDGET
    )


def test_frontier_selects_highest_priority_pending() -> None:
    low = _frontier_lead(priority=0.2)
    high = _frontier_lead(priority=0.9)
    blocked = _frontier_lead(status="BLOCKED", priority=1.0)
    selected, reason = select_next([low, blocked, high], max_depth=3)
    assert selected is not None
    assert selected.priority == 0.9
    assert reason == "highest_priority"


def test_frontier_skips_blocked_and_over_depth() -> None:
    selected, reason = select_next(
        [
            _frontier_lead(status="BLOCKED", priority=1.0),
            _frontier_lead(priority=0.8, depth=5),
        ],
        max_depth=2,
    )
    assert selected is None
    assert reason == "no_executable_leads"


def test_frontier_stops_without_budget() -> None:
    selected, reason = select_next(
        [_frontier_lead()], max_depth=3, budget_available=False
    )
    assert selected is None
    assert reason == "budget_exhausted"


def test_frontier_empty_means_no_work() -> None:
    selected, reason = select_next([], max_depth=3)
    assert selected is None
    assert reason == "no_executable_leads"
