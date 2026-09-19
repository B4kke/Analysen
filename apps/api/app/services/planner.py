"""NIM-backed planner that only proposes; the lead gate disposes.

The planner receives scope, frontier leads and budgets, and returns typed lead
proposals. Model output is validated against PlannerPlan and anything invalid
is rejected with a structured error — never persisted, never executed.

Data minimisation: the model sees target type/name, scope, leads and budgets.
Birth dates, national identifiers and raw evidence never leave the database.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from apps.api.app.core.config import get_settings
from apps.api.app.domain.planner import PlannerLeadProposal, PlannerPlan
from apps.api.app.domain.scope import ScopeSettings
from apps.api.app.services.source_router import supported_lead_types

_PROMPT_PATH = Path(__file__).resolve().parents[4] / "prompts" / "planner.md"

MAX_PROPOSALS_PER_CALL = 5


class ChatProvider(Protocol):
    async def chat_json(
        self,
        *,
        model: str,
        system: str,
        user: str,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        extra_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class PlannerContext:
    target_type: str
    target_name: str
    scope: ScopeSettings
    open_leads: list[dict[str, Any]]
    budgets: dict[str, Any]


class PlannerError(RuntimeError):
    pass


def _signature(proposal: PlannerLeadProposal) -> str:
    canonical = json.dumps(
        {
            "lead_type": proposal.lead_type,
            "scope_area": proposal.scope_area.value,
            "value": proposal.value,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _render_user(context: PlannerContext) -> str:
    enabled = [module.value for module in context.scope.scope_modules]
    return json.dumps(
        {
            "target": {"type": context.target_type, "name": context.target_name},
            "scope_modules": enabled,
            "expansion_policy": context.scope.expansion_policy.value,
            "max_relation_depth": context.scope.max_relation_depth,
            "open_leads": context.open_leads,
            "budgets": context.budgets,
            # Canonical tool/lead catalog: the planner may only propose lead
            # types the typed source router can execute. This list is built
            # from the router allowlist, never hardcoded here.
            "allowed_lead_types": sorted(supported_lead_types()),
            "instruction": (
                "Propose up to 5 next evidence-gathering leads as JSON: "
                '{"actions": [...]}. Each action needs lead_type, value, reason, '
                "information_need, scope_area, trigger_type, relation_depth, "
                "priority, expected_information_gain and optional "
                "originating_lead_id. Only propose inside the listed "
                "scope_modules. Only propose lead_type values from "
                "allowed_lead_types. Never invent identifiers or lead types."
            ),
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )


async def plan_next_actions(
    context: PlannerContext,
    provider: ChatProvider,
    *,
    model: str,
) -> list[PlannerLeadProposal]:
    """Ask the model for proposals and return only schema-valid ones.

    Raises PlannerError when the model output cannot be validated. Duplicate
    proposals inside one plan are dropped deterministically (first wins), so a
    looping model cannot multiply the same lead in a single call. A proposal
    whose lead_type is schema-valid but outside the typed router allowlist is
    rejected with the whole plan: the planner must never produce a lead the
    runtime cannot execute.
    """
    system = _PROMPT_PATH.read_text(encoding="utf-8")
    raw = await provider.chat_json(
        model=model,
        system=system,
        user=_render_user(context),
        max_tokens=2048,
        temperature=0.2,
    )
    try:
        plan = PlannerPlan.model_validate(raw)
    except Exception as exc:
        raise PlannerError(f"planner returned schema-invalid output: {exc}") from exc
    allowed = supported_lead_types()
    for proposal in plan.actions:
        if proposal.lead_type not in allowed:
            raise PlannerError(
                f"planner proposed unsupported lead_type: {proposal.lead_type!r}"
            )
    seen: set[str] = set()
    proposals: list[PlannerLeadProposal] = []
    for proposal in plan.actions[:MAX_PROPOSALS_PER_CALL]:
        signature = _signature(proposal)
        if signature in seen:
            continue
        seen.add(signature)
        proposals.append(proposal)
    return proposals


def proposal_to_lead_payload(proposal: PlannerLeadProposal) -> dict[str, Any]:
    """Shape a validated proposal for the gated /leads route."""
    return {
        "lead_type": proposal.lead_type,
        "value": proposal.value,
        "reason": proposal.reason,
        "priority": proposal.priority,
        "depth": proposal.relation_depth,
        "originating_claim_id": None,
        "scope_area": proposal.scope_area.value,
        "trigger_type": proposal.trigger_type.value,
        "information_need": proposal.information_need,
        "relation_depth": proposal.relation_depth,
    }


def planner_model_from_config(*, deep: bool = False) -> str:
    """Resolve the planner model from config/models.yaml roles."""
    settings = get_settings()
    models, _, _ = settings.validate_yaml_configs()
    role = models.roles["planner"]
    if deep and role.deep:
        return role.deep
    return role.primary
