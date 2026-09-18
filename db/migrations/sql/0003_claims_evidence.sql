-- Claims, Evidence, Documents, Sources, and Entity Resolution tables
-- Migration 0003: Adds full provenance pipeline

-- Sources table (registry of all data sources)
CREATE TABLE IF NOT EXISTS sources (
    id text PRIMARY KEY,
    name text NOT NULL,
    evidence_tier smallint,
    access_class text NOT NULL,
    base_url text,
    license text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- Documents table (raw documents with hash-addressed content)
CREATE TABLE IF NOT EXISTS documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id text NOT NULL REFERENCES sources(id),
    original_url text,
    canonical_url text,
    mime_type text,
    sha256 char(64) NOT NULL UNIQUE,
    raw_storage_key text,
    extracted_text text,
    parser_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    fetched_at timestamptz NOT NULL DEFAULT now()
);

-- Investigation-documents linkage
CREATE TABLE IF NOT EXISTS investigation_documents (
    investigation_id uuid NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    reason text NOT NULL DEFAULT 'direct_lookup',
    PRIMARY KEY (investigation_id, document_id)
);

-- Evidence table (immutable snippets from documents)
CREATE TABLE IF NOT EXISTS evidence (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    locator_type text NOT NULL,
    locator jsonb NOT NULL,
    excerpt text,
    structured_value jsonb,
    content_hash char(64) NOT NULL
);
CREATE INDEX IF NOT EXISTS evidence_document_idx ON evidence(document_id);

-- Claims table (assertions with status)
CREATE TABLE IF NOT EXISTS claims (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    investigation_id uuid NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    subject_entity_id uuid,
    predicate text NOT NULL,
    value jsonb,
    status text NOT NULL DEFAULT 'UNVERIFIED'
        CHECK (status IN ('VERIFIED', 'PARTIALLY_SUPPORTED', 'CONTRADICTED', 'INSUFFICIENT_EVIDENCE', 'UNVERIFIED')),
    created_at timestamptz NOT NULL DEFAULT now(),
    verified_at timestamptz
);
CREATE INDEX IF NOT EXISTS claims_investigation_idx ON claims(investigation_id);
CREATE INDEX IF NOT EXISTS claims_subject_idx ON claims(subject_entity_id);

-- Claim-Evidence linkage
CREATE TABLE IF NOT EXISTS claim_evidence (
    claim_id uuid NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    evidence_id uuid NOT NULL REFERENCES evidence(id) ON DELETE CASCADE,
    role text NOT NULL DEFAULT 'SUPPORTS'
        CHECK (role IN ('SUPPORTS', 'CONTRADICTS', 'PARTIAL')),
    PRIMARY KEY (claim_id, evidence_id)
);

-- Entity resolution tables
CREATE TABLE IF NOT EXISTS entities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    schema text NOT NULL,
    canonical_name text,
    attributes jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS entity_aliases (
    entity_id uuid NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    alias text NOT NULL,
    source_id text REFERENCES sources(id),
    confidence float NOT NULL DEFAULT 1.0,
    PRIMARY KEY (entity_id, alias)
);

CREATE TABLE IF NOT EXISTS entity_relations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_entity_id uuid NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    target_entity_id uuid NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    relation_type text NOT NULL,
    confidence float NOT NULL DEFAULT 1.0,
    evidence_ids uuid[] NOT NULL DEFAULT '{}',
    valid_from date,
    valid_to date
);
CREATE INDEX IF NOT EXISTS entity_relations_source_idx ON entity_relations(source_entity_id);
CREATE INDEX IF NOT EXISTS entity_relations_target_idx ON entity_relations(target_entity_id);

-- Investigation-entity linkage with expansion state
CREATE TABLE IF NOT EXISTS investigation_entities (
    investigation_id uuid NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    entity_id uuid NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    relation_depth smallint NOT NULL DEFAULT 0 CHECK (relation_depth BETWEEN 0 AND 3),
    expansion_state text NOT NULL DEFAULT 'CONTEXT_ONLY'
        CHECK (expansion_state IN ('TARGET', 'MATERIAL', 'CONTEXT_ONLY', 'BLOCKED', 'RESEARCHED')),
    material_reason text,
    discovered_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (investigation_id, entity_id)
);

-- Claim evidence resolution
CREATE TABLE IF NOT EXISTS claim_evidence_resolution (
    claim_id uuid NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    evidence_id uuid NOT NULL REFERENCES evidence(id) ON DELETE CASCADE,
    resolution text NOT NULL
        CHECK (resolution IN ('SUPPORTS', 'CONTRADICTS', 'PARTIAL', 'IRRELEVANT')),
    resolved_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (claim_id, evidence_id)
);

-- Entity resolution candidates
CREATE TABLE IF NOT EXISTS entity_resolution_candidates (
    investigation_id uuid NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    entity_id uuid NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    candidate_entity_id uuid NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    match_score float NOT NULL CHECK (match_score BETWEEN 0 AND 1),
    resolution_status text NOT NULL DEFAULT 'UNRESOLVED'
        CHECK (resolution_status IN ('MATCH', 'PROBABLE_MATCH', 'UNRESOLVED', 'NOT_MATCH')),
    negative_signals jsonb NOT NULL DEFAULT '[]'::jsonb,
    resolved_at timestamptz,
    PRIMARY KEY (investigation_id, entity_id, candidate_entity_id)
);

-- Search queries log
CREATE TABLE IF NOT EXISTS search_queries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    investigation_id uuid NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    originating_lead_id uuid REFERENCES leads(id) ON DELETE SET NULL,
    scope_area text,
    query_class text,
    query_text text NOT NULL,
    information_need text,
    reason text,
    results_count int NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (investigation_id, scope_area) REFERENCES investigation_modules(investigation_id, module) ON DELETE CASCADE
);

-- Evidence candidates for extraction pipeline
CREATE TABLE IF NOT EXISTS evidence_candidates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    investigation_id uuid NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    document_id uuid REFERENCES documents(id) ON DELETE SET NULL,
    locator_type text NOT NULL,
    locator jsonb NOT NULL,
    excerpt text,
    structured_value jsonb,
    proposed_predicate text,
    proposed_value jsonb,
    confidence float CHECK (confidence BETWEEN 0 AND 1),
    status text NOT NULL DEFAULT 'PROPOSED'
        CHECK (status IN ('PROPOSED', 'ACCEPTED', 'REJECTED', 'MERGED')),
    created_at timestamptz NOT NULL DEFAULT now()
);