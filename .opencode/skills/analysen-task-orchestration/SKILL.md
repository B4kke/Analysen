---
name: Analysen task orchestration
description: Decompose Analysen work into safe concurrent subagent workstreams, assign file ownership, dependencies and integration gates, and keep TASK_QUEUE/WORKLOG truthful.
---

# Workflow

1. Read `AGENTS.md`, `docs/TASK_QUEUE.md` and `docs/RECOVERY_ACTION_PLAN.md`.
2. Identify the smallest vertical outcome that can satisfy the active task.
3. Split only genuinely independent work. Prefer 2-5 concurrent subagents for cross-layer tasks.
4. Give each subagent:
   - exact task/AQ id,
   - files or subsystem it owns,
   - files it must not edit,
   - acceptance criteria,
   - tests it must run.
5. Keep shared integration files owned by the orchestrator unless one agent is explicitly assigned them.
6. After subagents return, inspect diffs and contracts. Do not merge conclusions blindly.
7. Run an integration-reviewer subagent before declaring P0 work DONE.
8. Mark DONE only after real acceptance criteria pass; if a previous DONE claim is disproved, reopen it.

# Concurrency rules

Good parallel pairs:
- schema/provenance + crawler/runtime,
- entity resolution + UI contract repairs after schema contracts are stable,
- verifier + report UX after claim statuses are stable,
- focused tests/review in parallel with implementation when they touch separate files.

Bad parallelism:
- two agents editing the same Alembic migration,
- two agents changing the same Pydantic/SQL contract independently,
- UI and API changing a request shape without one declared owner.

Use dependency waves rather than uncontrolled fan-out.
