"""Persist per-mention IIIF anchors (AQ-033).

IIIF Content Search anchors live on canvas URLs while fragment locators use
URN page identifiers, so the executor correlates them per page
(``match_page_anchors``: exact URN first, canvas fallback). The correlated
``xywh`` list is stored typed on the mention row as JSONB so mentions
without a validated crop still carry their text anchors next to the parent
page URN. Rows written before this migration keep NULL, which the report
builder maps to an empty list — never fabricated anchors.
"""
from alembic import op

revision = "0010_media_xywh"
down_revision = "0009_media_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE media_mentions
        ADD COLUMN IF NOT EXISTS xywh_anchors jsonb
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE media_mentions
        DROP COLUMN IF EXISTS xywh_anchors
    """)
