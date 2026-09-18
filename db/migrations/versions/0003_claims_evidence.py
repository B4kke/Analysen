"""Add claims, evidence, documents, sources, and entity resolution tables."""
from pathlib import Path

from alembic import op

revision = "0003_claims_evidence"
down_revision = "0002_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql = (Path(__file__).parents[1] / "sql" / "0003_claims_evidence.sql").read_text()
    for statement in sql.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    raise RuntimeError("Claims/evidence data must be retained. Restore a backup to roll back.")