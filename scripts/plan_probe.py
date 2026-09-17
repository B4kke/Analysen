"""Live NIM planner probe (phase 4).

Calls the real planner model once with a synthetic, non-personal context and
prints the validated proposals. Nothing is persisted and nothing is executed:
persistence always goes through the gated /leads route separately.

Usage:
    NIM_API_KEY=... python scripts/plan_probe.py [--deep]
"""

import argparse
import asyncio
import json
import sys

from apps.api.app.core.config import get_settings
from apps.api.app.domain.scope import ExpansionPolicy, ScopeModule, ScopeSettings
from apps.api.app.providers.nim import NIMProvider
from apps.api.app.services.planner import (
    PlannerContext,
    PlannerError,
    plan_next_actions,
    planner_model_from_config,
)


async def main(*, deep: bool) -> int:
    settings = get_settings()
    if not settings.nim_api_key:
        print("NIM_API_KEY is not set; refusing to call the model.", file=sys.stderr)
        return 2
    context = PlannerContext(
        target_type="company",
        target_name="Synthetic Probe AS",
        scope=ScopeSettings(
            scope_modules=[ScopeModule.WEB_MEDIA, ScopeModule.BUSINESS_ROLES],
            expansion_policy=ExpansionPolicy.DIRECT_RELATIONS,
            max_relation_depth=1,
        ),
        open_leads=[],
        budgets={"max_actions": 5},
    )
    model = planner_model_from_config(deep=deep)
    print(f"model: {model}")
    try:
        proposals = await plan_next_actions(
            context, NIMProvider(settings), model=model
        )
    except PlannerError as exc:
        print(f"REJECTED schema-invalid output: {exc}", file=sys.stderr)
        return 1
    print(f"proposals: {len(proposals)}")
    for proposal in proposals:
        print(
            json.dumps(
                {
                    "scope_area": proposal.scope_area.value,
                    "trigger_type": proposal.trigger_type.value,
                    "relation_depth": proposal.relation_depth,
                    "information_need": proposal.information_need,
                },
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--deep", action="store_true")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(deep=args.deep)))
