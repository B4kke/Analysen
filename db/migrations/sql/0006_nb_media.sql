-- National Library media mentions table (AQ-031).
--
-- Persists the canonical media_mention report contract fields so the
-- research pipeline can store and retrieve NB newspaper hits with full
-- provenance, access/license metadata, and identity state.
--
-- Idempotency: UNIQUE(investigation_id, page_urn, target_query) prevents
-- duplicate rows when the same pipeline runs multiple times.

CREATE TABLE IF NOT EXISTS media_mentions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    investigation_id uuid NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    target_query text NOT NULL,
    publication text,
    published_at date,
    page_number int,
    issue_urn text,
    page_urn text,
    headline text,
    summary text,
    text_excerpt text,
    text_availability text NOT NULL CHECK (text_availability IN ('FULL', 'PARTIAL_CONTEXT', 'UNAVAILABLE')),
    identity_state text NOT NULL DEFAULT 'UNRESOLVED',
    source_url text,
    access_class text,
    license_code text,
    image_document_id uuid REFERENCES documents(id) ON DELETE SET NULL,
    image_embeddable boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS media_mentions_investigation_idx
    ON media_mentions(investigation_id);

CREATE INDEX IF NOT EXISTS media_mentions_published_idx
    ON media_mentions(investigation_id, published_at, page_number);

-- Idempotency constraint: same investigation + same NB page + same query
-- must not create duplicate rows on rerun.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'media_mentions_idempotency_key'
    ) THEN
        ALTER TABLE media_mentions
            ADD CONSTRAINT media_mentions_idempotency_key
            UNIQUE (investigation_id, page_urn, target_query);
    END IF;
END $$;