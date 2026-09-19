"""Deterministic lead admission: discovery and LLM output cannot grant scope.

Every proposed lead must satisfy the investigation's stored scope before it can
be persisted as PENDING. Leads that fail the gate are persisted as BLOCKED with
an explicit machine-readable reason so audit trails show what was refused and
why. Nothing in this module calls a model.
"""


from apps.api.app.domain.models import Lead
from apps.api.app.domain.scope import (
    ExpansionPolicy,
    ExpansionState,
    ScopeSettings,
    TriggerType,
)
from apps.api.app.services.scope_gate import check_research_scope

# Discovery-derived triggers never authorize research on their own.
_PASSIVE_TRIGGERS = frozenset(
    {
        TriggerType.NEW_VERIFIED_ALIAS,
        TriggerType.MEDIA_CORROBORATION,
        TriggerType.SANCTIONS_CANDIDATE,
    }
)


def gate_lead(
    scope: ScopeSettings,
    lead: Lead,
    *,
    expansion_state: ExpansionState = ExpansionState.TARGET,
    verified_relation: bool = True,
    material_reason: str | None = None,
    source_enabled: bool = True,
    policy_allowed: bool = True,
    budget_available: bool = True,
) -> str | None:
    """Return a blocked_reason for a lead that may not run, else None.

    A passive discovery trigger can never be scheduled by itself; it is stored
    as a lead for human/trigger evaluation instead of auto-execution. Relation
    leads (non-target depth) must still prove a verified relation; the default
    here is the target entity, which the investigation already authorizes.
    """
    if lead.trigger_type in _PASSIVE_TRIGGERS:
        # A passive discovery lead is never directly executable: even when it
        # concerns the target it must go through trigger evaluation first.
        return "passive_trigger_requires_review"

    if scope.expansion_policy == ExpansionPolicy.CONTEXT_ONLY and expansion_state not in (
        ExpansionState.TARGET,
    ):
        return "context_only_policy"

    decision = check_research_scope(
        scope,
        module=lead.scope_area,
        information_need=lead.information_need,
        expansion_state=expansion_state,
        relation_depth=lead.relation_depth,
        verified_relation=verified_relation,
        material_reason=material_reason,
        source_enabled=source_enabled,
        policy_allowed=policy_allowed,
        budget_available=budget_available,
    )
    if decision.allowed:
        return None
    return decision.reason
