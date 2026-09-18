---
name: Analysen database migrations
description: Repair or evolve Analysen PostgreSQL/Alembic schema safely, including baseline compatibility, repository contracts, idempotency and real migration integration tests.
---

# Invariants

- Alembic is the migration authority.
- `db/schema.sql` is reference documentation, not a second migration engine.
- `CREATE TABLE IF NOT EXISTS` never substitutes for required ALTER statements on existing tables.
- Repository SQL, Pydantic models and database constraints must agree on field names, status enums, nullability and uniqueness.
- Forward migrations preserve existing investigation/provenance data unless an explicit ADR says otherwise.

# Required verification

For migration work:
1. create a fresh scratch database,
2. apply baseline then `alembic upgrade head`,
3. verify expected columns/constraints,
4. apply `upgrade head` again,
5. persist a representative real repository object graph,
6. read it back and assert constraints/provenance,
7. test upgrade from a legacy fixture when the migration modifies an existing table.

Never call a migration task DONE using only unit tests that mock SQL.
