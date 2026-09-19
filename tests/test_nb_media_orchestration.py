"""NB orchestration wiring contract (AQ-031): pure unit tests, no database.

Covers the deterministic seams owned by the orchestration wiring:
trigger enum, typed router allowlist, planner lead catalog built on the
router, planner rejection of runtime-unsupported lead types, the seed lead
shape, and executor bounds. Network and persistence seams are faked in the
DB-backed integration tests; no live NB is ever touched here.
"""

from typing import Any

import pytest

from apps.api.app.domain.scope import ScopeModule, TriggerType
from apps.api.app.services.planner import PlannerContext, PlannerError, plan_next_actions
from apps.api.app.services.research_loop import build_nb_seed_lead, build_nb_seed_leads
from apps.api.app.services.source_router import (
    EXECUTOR_ROUTES,
    route_lead,
    supported_lead_types,
)


def test_direct_source_lookup_trigger_exists_without_removing_old_values() -> None:
    assert TriggerType.DIRECT_SOURCE_LOOKUP.value == "DIRECT_SOURCE_LOOKUP"
    for value in (
        "IDENTITY_AMBIGUITY",
        "NEW_VERIFIED_ALIAS",
        "MATERIAL_RELATION",
        "WEAK_SOURCE_ONLY",
        "CONTRADICTION",
        "TEMPORAL_GAP",
        "FINANCIAL_ANOMALY",
        "DOCUMENT_QUALITY",
        "DOMAIN_RELEVANCE",
        "MEDIA_CORROBORATION",
        "SANCTIONS_CANDIDATE",
    ):
        assert TriggerType(value).value == value


def test_direct_source_lookup_is_not_a_passive_trigger() -> None:
    from apps.api.app.services.lead_gate import _PASSIVE_TRIGGERS as gate_passive
    from apps.api.app.services.trigger_evaluator import (
        _PASSIVE_TRIGGERS as evaluator_passive,
    )

    assert TriggerType.DIRECT_SOURCE_LOOKUP not in gate_passive
    assert TriggerType.DIRECT_SOURCE_LOOKUP not in evaluator_passive


def test_nb_newspaper_search_is_allowlisted_to_nb_media() -> None:
    assert EXECUTOR_ROUTES["nb_newspaper_search"] == "nb_media"
    assert route_lead("nb_newspaper_search") == "nb_media"
    assert "nb_newspaper_search" in supported_lead_types()


class _FakeProvider:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    async def chat_json(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.payload


def _context() -> PlannerContext:
    from apps.api.app.domain.scope import ExpansionPolicy, ScopeSettings

    return PlannerContext(
        target_type="person",
        target_name="Seed Probe",
        scope=ScopeSettings(
            scope_modules=[ScopeModule.WEB_MEDIA],
            expansion_policy=ExpansionPolicy.CONTEXT_ONLY,
            max_relation_depth=0,
        ),
        open_leads=[],
        budgets={"budget_available": True},
    )


def _proposal_dict(**overrides: Any) -> dict[str, Any]:
    payload = {
        "lead_type": "nb_newspaper_search",
        "value": {"query": "Seed Probe", "query_class": "ENTITY_ALIAS_EXACT"},
        "reason": "Baseline newspaper lookup for the person target",
        "information_need": "Find newspaper mentions of the target person",
        "scope_area": "WEB_MEDIA",
        "trigger_type": "DIRECT_SOURCE_LOOKUP",
        "relation_depth": 0,
        "priority": 0.7,
        "expected_information_gain": "Locates dated newspaper mentions either way",
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_planner_accepts_allowlisted_nb_lead() -> None:
    provider = _FakeProvider({"actions": [_proposal_dict()]})
    proposals = await plan_next_actions(_context(), provider, model="m")
    assert len(proposals) == 1
    assert proposals[0].lead_type == "nb_newspaper_search"
    assert proposals[0].trigger_type == TriggerType.DIRECT_SOURCE_LOOKUP


@pytest.mark.asyncio
async def test_planner_rejects_schema_valid_but_runtime_unsupported_lead() -> None:
    provider = _FakeProvider(
        {"actions": [_proposal_dict(lead_type="crawl_entire_internet")]}
    )
    with pytest.raises(PlannerError, match="unsupported lead_type"):
        await plan_next_actions(_context(), provider, model="m")


@pytest.mark.asyncio
async def test_planner_user_message_carries_router_allowlist_as_catalog() -> None:
    import json

    provider = _FakeProvider({"actions": [_proposal_dict()]})
    await plan_next_actions(_context(), provider, model="m")
    user_payload = json.loads(provider.calls[0]["user"])
    assert user_payload["allowed_lead_types"] == sorted(supported_lead_types())
    assert "nb_newspaper_search" in user_payload["allowed_lead_types"]
    assert "crawl_entire_internet" not in user_payload["allowed_lead_types"]


@pytest.mark.asyncio
async def test_planner_rejects_plan_when_any_action_is_unsupported() -> None:
    provider = _FakeProvider(
        {
            "actions": [
                _proposal_dict(),
                _proposal_dict(
                    lead_type="web_media_lookup",
                    value={"url": "https://example.com/x"},
                ),
            ]
        }
    )
    with pytest.raises(PlannerError, match="unsupported lead_type"):
        await plan_next_actions(_context(), provider, model="m")


def test_build_nb_seed_lead_shape() -> None:
    lead = build_nb_seed_lead("Maylen Sorkness Andersen")
    assert lead is not None
    assert lead.lead_type == "nb_newspaper_search"
    assert lead.value == {
        "query": "Maylen Sorkness Andersen",
        "query_class": "ENTITY_ALIAS_EXACT",
    }
    assert lead.scope_area == ScopeModule.WEB_MEDIA
    assert lead.trigger_type == TriggerType.DIRECT_SOURCE_LOOKUP
    assert lead.relation_depth == 0
    assert lead.depth == 0
    assert len(lead.information_need) >= 3


def test_build_nb_seed_lead_rejects_blank_or_short_names() -> None:
    assert build_nb_seed_lead("") is None
    assert build_nb_seed_lead("  ") is None
    assert build_nb_seed_lead("Ab") is None
    lead = build_nb_seed_lead("  Ola Nordmann  ")
    assert lead is not None
    assert lead.value["query"] == "Ola Nordmann"


def test_build_nb_seed_leads_dedups_target_and_verified_aliases() -> None:
    leads = build_nb_seed_leads(
        ["Maylen Sorkness Andersen", "  maylen sorkness andersen  ", "Ab", ""]
    )
    assert len(leads) == 1
    assert leads[0].value["query"] == "Maylen Sorkness Andersen"

    leads = build_nb_seed_leads(["Ola Nordmann", "Kari Nordmann", "Kari Nordmann"])
    assert [lead.value["query"] for lead in leads] == ["Ola Nordmann", "Kari Nordmann"]
    for lead in leads:
        assert lead.lead_type == "nb_newspaper_search"
        assert lead.scope_area == ScopeModule.WEB_MEDIA
        assert lead.trigger_type == TriggerType.DIRECT_SOURCE_LOOKUP
        # Verified aliases reuse the direct-source trigger: the passive
        # NEW_VERIFIED_ALIAS trigger would park the lead as BLOCKED and it
        # would never run.
        assert lead.trigger_type.value != "NEW_VERIFIED_ALIAS"
        assert lead.relation_depth == 0
        assert lead.value["query_class"] == "ENTITY_ALIAS_EXACT"


def test_nb_seed_scope_gate_blocks_without_web_media() -> None:
    from apps.api.app.domain.scope import ExpansionPolicy, ScopeSettings
    from apps.api.app.services.lead_gate import gate_lead

    scope = ScopeSettings(
        scope_modules=[],
        expansion_policy=ExpansionPolicy.CONTEXT_ONLY,
        max_relation_depth=0,
    )
    lead = build_nb_seed_lead("Ola Nordmann")
    assert lead is not None
    assert gate_lead(scope, lead) == "module_disabled"


def test_executor_bounds_match_national_library_contract() -> None:
    from apps.api.app.services.executors import nb_media

    assert nb_media.MAX_ISSUES_PER_QUERY == 25
    assert nb_media.MAX_PAGES_PER_ISSUE == 5
    assert nb_media.LEAD_TYPE == "nb_newspaper_search"
    assert nb_media.PROVIDER == "nb_catalog"
