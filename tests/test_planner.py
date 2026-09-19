"""Planner service contract (phase 4).

The planner proposes; the deterministic lead gate disposes. Model output must
be schema-valid or it is rejected before anything is persisted.
"""

from typing import Any

import pytest

from apps.api.app.domain.planner import PlannerLeadProposal, PlannerPlan
from apps.api.app.domain.scope import ExpansionPolicy, ScopeModule, ScopeSettings
from apps.api.app.services.planner import (
    PlannerContext,
    PlannerError,
    plan_next_actions,
    planner_model_from_config,
    proposal_to_lead_payload,
)


def _context(*modules: ScopeModule) -> PlannerContext:
    return PlannerContext(
        target_type="company",
        target_name="Plan Probe AS",
        scope=ScopeSettings(
            scope_modules=list(modules),
            expansion_policy=ExpansionPolicy.DIRECT_RELATIONS,
            max_relation_depth=1,
        ),
        open_leads=[],
        budgets={"max_actions": 5},
    )


class _FakeProvider:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    async def chat_json(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.payload


def _proposal_dict(**overrides: Any) -> dict[str, Any]:
    payload = {
        "lead_type": "web_document_fetch",
        "value": {"url": "https://example.com/article"},
        "reason": "Independent confirmation of registered status",
        "information_need": "Confirm registered status from a secondary source",
        "scope_area": "WEB_MEDIA",
        "trigger_type": "CONTRADICTION",
        "relation_depth": 0,
        "priority": 0.6,
        "expected_information_gain": "Resolves the status contradiction either way",
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_valid_plan_returns_typed_proposals() -> None:
    provider = _FakeProvider({"actions": [_proposal_dict()]})
    proposals = await plan_next_actions(
        _context(ScopeModule.WEB_MEDIA), provider, model="test-model"
    )
    assert len(proposals) == 1
    assert isinstance(proposals[0], PlannerLeadProposal)
    assert proposals[0].scope_area == ScopeModule.WEB_MEDIA
    assert provider.calls[0]["model"] == "test-model"
    assert provider.calls[0]["temperature"] == 0.2


@pytest.mark.asyncio
async def test_schema_invalid_output_is_rejected() -> None:
    provider = _FakeProvider({"actions": [{"lead_type": "x"}]})
    with pytest.raises(PlannerError, match="schema-invalid"):
        await plan_next_actions(_context(ScopeModule.WEB_MEDIA), provider, model="m")


@pytest.mark.asyncio
async def test_non_object_output_is_rejected() -> None:
    provider = _FakeProvider({"actions": "not-a-list"})  # type: ignore[dict-item]
    with pytest.raises(PlannerError, match="schema-invalid"):
        await plan_next_actions(_context(ScopeModule.WEB_MEDIA), provider, model="m")


@pytest.mark.asyncio
async def test_extra_fields_are_rejected() -> None:
    provider = _FakeProvider(
        {"actions": [_proposal_dict(surprise_field="injection")]}
    )
    with pytest.raises(PlannerError, match="schema-invalid"):
        await plan_next_actions(_context(ScopeModule.WEB_MEDIA), provider, model="m")


@pytest.mark.asyncio
async def test_duplicate_proposals_are_deduplicated() -> None:
    provider = _FakeProvider({"actions": [_proposal_dict(), _proposal_dict()]})
    proposals = await plan_next_actions(
        _context(ScopeModule.WEB_MEDIA), provider, model="m"
    )
    assert len(proposals) == 1


@pytest.mark.asyncio
async def test_proposal_cap_is_enforced() -> None:
    provider = _FakeProvider(
        {
            "actions": [
                _proposal_dict(value={"url": f"https://example.com/{index}"})
                for index in range(8)
            ]
        }
    )
    proposals = await plan_next_actions(
        _context(ScopeModule.WEB_MEDIA), provider, model="m"
    )
    assert len(proposals) == 5


def test_planner_validation_does_not_enforce_scope() -> None:
    # Scope enforcement belongs to the deterministic lead gate, not to output
    # validation: an out-of-scope proposal is well-formed and must still reach
    # the gate, which refuses and audits it.
    plan = PlannerPlan.model_validate(
        {"actions": [_proposal_dict(scope_area="SANCTIONS")]}
    )
    assert plan.actions[0].scope_area == ScopeModule.SANCTIONS


def test_proposal_converts_to_gated_lead_payload() -> None:
    proposal = PlannerLeadProposal.model_validate(_proposal_dict())
    payload = proposal_to_lead_payload(proposal)
    assert payload["scope_area"] == "WEB_MEDIA"
    assert payload["trigger_type"] == "CONTRADICTION"
    assert payload["depth"] == 0
    assert payload["originating_claim_id"] is None


def test_planner_model_comes_from_config() -> None:
    assert planner_model_from_config() == "nvidia/nemotron-3-super-120b-a12b"
    assert planner_model_from_config(deep=True) == "nvidia/nemotron-3-ultra-550b-a55b"
