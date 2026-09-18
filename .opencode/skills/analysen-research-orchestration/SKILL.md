---
name: Analysen research orchestration
description: Connect planner, lead gate, trigger evaluator, frontier, source router, executors, checkpointing, budgets and stop rules into one bounded research pass.
---

# Target loop

A new investigation with active scope should be able to progress:

1. load current investigation/scope/coverage,
2. inspect admitted frontier,
3. when appropriate and frontier lacks useful work, call typed planner,
4. validate and gate proposals,
5. persist admitted/blocked proposals with audit,
6. select next lead using investigation limits,
7. trigger-evaluate,
8. source-route to an allowlisted executor,
9. fetch and persist provenance,
10. extract/verify as applicable,
11. update coverage and checkpoint,
12. continue until a deterministic stop condition.

# Hard boundaries

- Planner proposes; code authorizes.
- Source routing is explicit, not arbitrary tool choice.
- Use stored `max_relation_depth`; never replace it with a permissive constant.
- Discovery of a new entity does not authorize research on it.
- A worker restart must not duplicate terminal fetches.
- Repeated query/result signatures must stop.
- Budget/lead/document/time caps must be enforceable by code.

Build the loop incrementally with E2E tests, not by adding disconnected helper classes.
