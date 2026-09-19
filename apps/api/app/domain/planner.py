"""Typed planner proposals (phase 4).

The planner is advisory only: it proposes leads, and the deterministic lead
gate decides what may run. These schemas define the exact shape the model must
return; anything else is rejected before it can reach the gate.
"""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from apps.api.app.domain.scope import ScopeModule, TriggerType


class PlannerLeadProposal(BaseModel):
    """One evidence-gathering proposal from the planner model."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    lead_type: str = Field(min_length=1, max_length=100)
    value: Any
    reason: str = Field(min_length=3, max_length=2000)
    information_need: str = Field(min_length=3, max_length=2000)
    scope_area: ScopeModule
    trigger_type: TriggerType
    relation_depth: int = Field(default=0, ge=0, le=3)
    priority: float = Field(default=0.5, ge=0, le=1)
    expected_information_gain: str = Field(min_length=3, max_length=1000)
    originating_lead_id: UUID | None = None


class PlannerPlan(BaseModel):
    """The complete planner response: a bounded list of proposals."""

    model_config = ConfigDict(extra="forbid")

    # No length cap here: the service truncates deterministically so one extra
    # proposal cannot invalidate the whole plan.
    actions: list[PlannerLeadProposal] = Field(default_factory=list)
