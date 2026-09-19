"""Rescope claim fingerprints to include the subject identity (AQ-030).

The fingerprint formula gains the canonical subject segment so two different
entities with the same predicate/value keep separate claims. The formula is
frozen here (copied, not imported: migrations must not depend on evolving
application code):

    sha256("{investigation_id}:{subject}:{predicate}:{canonical_json}").

Existing rows are recomputed in place, preserving ids and therefore all
evidence links. Recomputation is injective over legacy rows: the old formula
could not produce two rows differing only by subject (its UNIQUE would have
merged them), so no new collisions can arise.
"""
import contextlib
import hashlib
import json
from typing import Any
from uuid import UUID

from alembic import op
from sqlalchemy import text

revision = "0005_claim_fingerprint_subject"
down_revision = "0004_claims_reconcile"
branch_labels = None
depends_on = None


def _frozen_fingerprint(
    investigation_id: UUID, subject_entity_id: UUID | None, predicate: str, value: Any
) -> str:
    if isinstance(value, str):
        with contextlib.suppress(json.JSONDecodeError):
            value = json.loads(value)
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    subject_key = str(subject_entity_id) if subject_entity_id is not None else ""
    return hashlib.sha256(
        f"{investigation_id}:{subject_key}:{predicate}:{canonical}".encode()
    ).hexdigest()


def upgrade() -> None:
    bind = op.get_bind()
    rows = (
        bind.execute(
            text(
                "SELECT id, investigation_id, subject_entity_id, predicate, value FROM claims"
            )
        )
        .mappings()
        .all()
    )
    for row in rows:
        new_fingerprint = _frozen_fingerprint(
            row["investigation_id"],
            row["subject_entity_id"],
            row["predicate"],
            row["value"],
        )
        bind.execute(
            text("UPDATE claims SET fingerprint = :fp WHERE id = :id"),
            {"fp": new_fingerprint, "id": row["id"]},
        )


def downgrade() -> None:
    raise RuntimeError("Claims/evidence data must be retained. Restore a backup to roll back.")
