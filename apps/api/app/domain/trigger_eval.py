"""Typed trigger evaluation outcomes (AQ-012).

The trigger evaluator decides what a finding, gap or contradiction becomes:
a follow-up lead, a targeted verification lead, context-only storage, a scope
refusal, or an explicit stop. The executor (later) only runs FOLLOW_UP_LEAD
and VERIFICATION_LEAD that also pass the lead gate.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from apps.api.app.domain.models import Lead


class TriggerDecision(StrEnum):
    FOLLOW_UP_LEAD = "FOLLOW_UP_LEAD"
    VERIFICATION_LEAD = "VERIFICATION_LEAD"
    CONTEXT_ONLY = "CONTEXT_ONLY"
    BLOCKED_BY_SCOPE = "BLOCKED_BY_SCOPE"
    STOP_SUFFICIENT = "STOP_SUFFICIENT"
    STOP_LOW_VALUE = "STOP_LOW_VALUE"
    STOP_BUDGET = "STOP_BUDGET"


class TriggerEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    decision: TriggerDecision
    reason: str = Field(min_length=3, max_length=1000)


class FrontierLead(Lead):
    """A persisted lead candidate with its execution status."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    status: str = Field(min_length=1, max_length=20)
