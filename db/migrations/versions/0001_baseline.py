"""Version the original schema; adopts existing schema.sql installations without data loss."""
from pathlib import Path

from alembic import op

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql = (Path(__file__).parents[1] / "sql" / "0001_baseline.sql").read_text()
    # This immutable DDL snapshot contains no procedural bodies or embedded semicolons.
    for statement in sql.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    raise RuntimeError("Forward-only baseline: restore a database backup to roll back.")
