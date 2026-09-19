"""Deduplicate NULL page_urn media mentions (AQ-031).

The 0006_nb_media idempotency key used a default UNIQUE constraint, which
treats NULLs as distinct (NULLS DISTINCT). Issue-level NB mentions with
page_urn IS NULL therefore bypassed the ON CONFLICT arbiter and duplicated
on every rerun. PostgreSQL 15+ (deployment runs PG17) supports
UNIQUE NULLS NOT DISTINCT, so the same (investigation_id, page_urn,
target_query) arbiter now matches NULL rows too.

Upgrade dedupes pre-existing NULL duplicates (keeping the earliest row per
key) before replacing the constraint, so legacy databases migrate cleanly.
"""
from alembic import op

revision = "0008_media_nulls"
down_revision = "0007_direct_source_lookup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DELETE FROM media_mentions a
        USING media_mentions b
        WHERE a.page_urn IS NULL
          AND b.page_urn IS NULL
          AND a.investigation_id = b.investigation_id
          AND a.target_query = b.target_query
          AND (a.created_at, a.id) > (b.created_at, b.id)
    """)
    op.execute("""
        ALTER TABLE media_mentions
        DROP CONSTRAINT IF EXISTS media_mentions_idempotency_key
    """)
    op.execute("""
        ALTER TABLE media_mentions
        ADD CONSTRAINT media_mentions_idempotency_key
        UNIQUE NULLS NOT DISTINCT (investigation_id, page_urn, target_query)
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE media_mentions
        DROP CONSTRAINT IF EXISTS media_mentions_idempotency_key
    """)
    op.execute("""
        ALTER TABLE media_mentions
        ADD CONSTRAINT media_mentions_idempotency_key
        UNIQUE (investigation_id, page_urn, target_query)
    """)
