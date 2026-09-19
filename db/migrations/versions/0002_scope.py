"""Persist explicit scope, module coverage, entity permissions and research metadata."""
from pathlib import Path

from alembic import op

revision = "0002_scope"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql = (Path(__file__).parents[1] / "sql" / "0002_scope.sql").read_text()
    for statement in sql.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    raise RuntimeError("Scope/audit data must be retained. Restore a backup to roll back.")
