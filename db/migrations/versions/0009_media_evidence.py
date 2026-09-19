"""Link media mentions to their crop evidence (AQ-032).

The NB executor already persists a validated article crop as Document +
Evidence, but ``media_mentions`` only referenced the derived document via
``image_document_id``. The report contract (docs/NATIONAL_LIBRARY.md)
requires per-mention ``citations``, so mentions need a direct, honest link
to the evidence row that backs them. Mentions without stored evidence keep
``evidence_id`` NULL and render an empty citation list — never fabricated
links.
"""
from alembic import op

revision = "0009_media_evidence"
down_revision = "0008_media_nulls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE media_mentions
        ADD COLUMN IF NOT EXISTS evidence_id uuid
        REFERENCES evidence(id) ON DELETE SET NULL
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE media_mentions
        DROP COLUMN IF EXISTS evidence_id
    """)
