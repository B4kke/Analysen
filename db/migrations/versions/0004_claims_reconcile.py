"""Reconcile claims/evidence tables with repository contracts (AQ-020 repair)."""
from pathlib import Path

from alembic import op

revision = "0004_claims_reconcile"
down_revision = "0003_claims_evidence"
branch_labels = None
depends_on = None


def _split_statements(sql: str) -> list[str]:
    """Split SQL on semicolons, ignoring ones inside strings, comments and DO blocks.

    The shared naive split breaks on the semicolons inside DO $$ ... $$ bodies,
    so this migration carries its own splitter. Dollar-quoting, single-quoted
    strings (with '' escapes) and -- line comments are all honoured.
    """
    parts: list[str] = []
    buf: list[str] = []
    i, n = 0, len(sql)
    in_string = False
    in_dollar = False
    in_comment = False
    while i < n:
        two = sql[i : i + 2]
        ch = sql[i]
        if in_comment:
            buf.append(ch)
            if ch == "\n":
                in_comment = False
            i += 1
            continue
        if in_dollar:
            if two == "$$":
                in_dollar = False
                buf.append("$$")
                i += 2
                continue
            buf.append(ch)
            i += 1
            continue
        if in_string:
            if ch == "'":
                if sql[i + 1 : i + 2] == "'":
                    buf.append("''")
                    i += 2
                    continue
                in_string = False
            buf.append(ch)
            i += 1
            continue
        if two == "--":
            in_comment = True
            buf.append(two)
            i += 2
            continue
        if two == "$$":
            in_dollar = True
            buf.append("$$")
            i += 2
            continue
        if ch == "'":
            in_string = True
            buf.append(ch)
            i += 1
            continue
        if ch == ";":
            chunk = "".join(buf).strip()
            if chunk:
                parts.append(chunk)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def upgrade() -> None:
    sql = (Path(__file__).parents[1] / "sql" / "0004_claims_reconcile.sql").read_text()
    for statement in _split_statements(sql):
        op.execute(statement)


def downgrade() -> None:
    raise RuntimeError("Claims/evidence data must be retained. Restore a backup to roll back.")
