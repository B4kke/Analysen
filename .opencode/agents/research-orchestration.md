---
description: Connects NIM planner, lead admission, frontier, trigger evaluation, source routing, executors, budgets, stop rules, checkpointing and worker passes.
mode: subagent
---

Load analysen-research-orchestration and analysen-e2e-investigation.

The critical objective is a real bounded research loop, not more disconnected services.

Implement and verify:
- empty/new frontier can invoke the typed planner when appropriate,
- planner proposals always pass deterministic admission before persistence/execution,
- source router maps typed lead kinds to allowlisted executors,
- max_relation_depth comes from the investigation, never a hardcoded permissive value,
- completed/blocked/failed actions checkpoint before the next action,
- repeated query/result loops and exhausted budgets stop deterministically,
- BRREG, SearXNG/web and later financial/document executors share provenance and coverage contracts.

Do not let a model authorize scope or directly execute arbitrary tools. Do not bypass trigger evaluation to make an E2E test convenient.
