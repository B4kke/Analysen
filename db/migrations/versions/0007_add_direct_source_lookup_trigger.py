"""Add DIRECT_SOURCE_LOOKUP trigger type to leads check constraint (AQ-031).

The Nasjonalbiblioteket media pipeline adds a new trigger type for deterministic
NB newspaper search leads that bypasses the planner.
"""
from alembic import op

revision = "0007_direct_source_lookup"
down_revision = "0006_nb_media"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add DIRECT_SOURCE_LOOKUP to the trigger_type check constraint
    op.execute("""
        ALTER TABLE leads
        DROP CONSTRAINT leads_trigger_type_check
    """)
    op.execute("""
        ALTER TABLE leads
        ADD CONSTRAINT leads_trigger_type_check
        CHECK (trigger_type = ANY (ARRAY[
            'IDENTITY_AMBIGUITY',
            'NEW_VERIFIED_ALIAS',
            'MATERIAL_RELATION',
            'WEAK_SOURCE_ONLY',
            'CONTRADICTION',
            'TEMPORAL_GAP',
            'FINANCIAL_ANOMALY',
            'DOCUMENT_QUALITY',
            'DOMAIN_RELEVANCE',
            'MEDIA_CORROBORATION',
            'SANCTIONS_CANDIDATE',
            'DIRECT_SOURCE_LOOKUP'
        ]::text[]))
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE leads
        DROP CONSTRAINT leads_trigger_type_check
    """)
    op.execute("""
        ALTER TABLE leads
        ADD CONSTRAINT leads_trigger_type_check
        CHECK (trigger_type = ANY (ARRAY[
            'IDENTITY_AMBIGUITY',
            'NEW_VERIFIED_ALIAS',
            'MATERIAL_RELATION',
            'WEAK_SOURCE_ONLY',
            'CONTRADICTION',
            'TEMPORAL_GAP',
            'FINANCIAL_ANOMALY',
            'DOCUMENT_QUALITY',
            'DOMAIN_RELEVANCE',
            'MEDIA_CORROBORATION',
            'SANCTIONS_CANDIDATE'
        ]::text[]))
    """)
