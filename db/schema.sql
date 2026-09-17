CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS investigations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  target_type text NOT NULL CHECK (target_type IN ('person','organization','company','domain')),
  target_input jsonb NOT NULL,
  purpose text NOT NULL,
  legal_basis_note text,
  status text NOT NULL DEFAULT 'CREATED',
  budgets jsonb NOT NULL DEFAULT '{}'::jsonb,
  retention_until timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sources (
  id text PRIMARY KEY,
  name text NOT NULL,
  evidence_tier smallint,
  access_class text NOT NULL,
  base_url text,
  license text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS entities (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  schema text NOT NULL,
  canonical_name text,
  normalized_name text,
  attributes jsonb NOT NULL DEFAULT '{}'::jsonb,
  resolution_state text NOT NULL DEFAULT 'UNRESOLVED',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS entities_name_trgm ON entities USING gin (normalized_name gin_trgm_ops);

CREATE TABLE IF NOT EXISTS entity_aliases (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_id uuid NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  alias text NOT NULL,
  normalized_alias text NOT NULL,
  source_id text REFERENCES sources(id),
  evidence_id uuid,
  valid_from date,
  valid_to date
);
CREATE INDEX IF NOT EXISTS aliases_norm_idx ON entity_aliases(normalized_alias);

CREATE TABLE IF NOT EXISTS documents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  investigation_id uuid REFERENCES investigations(id) ON DELETE CASCADE,
  source_id text REFERENCES sources(id),
  original_url text,
  canonical_url text,
  mime_type text,
  title text,
  publisher text,
  published_at timestamptz,
  fetched_at timestamptz NOT NULL DEFAULT now(),
  sha256 char(64) NOT NULL,
  raw_storage_key text,
  extracted_text text,
  parser_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE(sha256)
);
CREATE INDEX IF NOT EXISTS documents_url_idx ON documents(canonical_url);

CREATE TABLE IF NOT EXISTS evidence (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  locator_type text NOT NULL,
  locator jsonb NOT NULL,
  excerpt text,
  structured_value jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE entity_aliases
  ADD CONSTRAINT entity_aliases_evidence_fk
  FOREIGN KEY (evidence_id) REFERENCES evidence(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS claims (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  investigation_id uuid NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
  subject_entity_id uuid REFERENCES entities(id),
  predicate text NOT NULL,
  object_entity_id uuid REFERENCES entities(id),
  value jsonb,
  valid_from date,
  valid_to date,
  status text NOT NULL DEFAULT 'UNVERIFIED_LEAD',
  confidence_components jsonb NOT NULL DEFAULT '{}'::jsonb,
  generated_by text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS claim_evidence (
  claim_id uuid NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
  evidence_id uuid NOT NULL REFERENCES evidence(id) ON DELETE CASCADE,
  relation text NOT NULL CHECK (relation IN ('supports','contradicts','context')),
  PRIMARY KEY (claim_id, evidence_id, relation)
);

CREATE TABLE IF NOT EXISTS relationships (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  subject_entity_id uuid NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  predicate text NOT NULL,
  object_entity_id uuid NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  valid_from date,
  valid_to date,
  resolution_state text NOT NULL DEFAULT 'UNRESOLVED',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS relationship_evidence (
  relationship_id uuid NOT NULL REFERENCES relationships(id) ON DELETE CASCADE,
  evidence_id uuid NOT NULL REFERENCES evidence(id) ON DELETE CASCADE,
  PRIMARY KEY (relationship_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS leads (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  investigation_id uuid NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
  lead_type text NOT NULL,
  entity_id uuid REFERENCES entities(id),
  value jsonb,
  reason text NOT NULL,
  originating_claim_id uuid REFERENCES claims(id),
  priority real NOT NULL DEFAULT 0.5,
  depth integer NOT NULL DEFAULT 0,
  status text NOT NULL DEFAULT 'OPEN',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS leads_frontier_idx ON leads(investigation_id, status, priority DESC);

CREATE TABLE IF NOT EXISTS contradictions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  investigation_id uuid NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
  claim_a_id uuid NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
  claim_b_id uuid NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
  contradiction_type text NOT NULL,
  explanation text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS brreg_role_index (
  id bigserial PRIMARY KEY,
  normalized_name text NOT NULL,
  display_name text NOT NULL,
  birth_date date,
  orgnr char(9) NOT NULL,
  role_code text NOT NULL,
  role_description text,
  raw_record jsonb NOT NULL,
  source_snapshot_hash char(64) NOT NULL,
  imported_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS brreg_role_name_birth_idx ON brreg_role_index(normalized_name, birth_date);
CREATE INDEX IF NOT EXISTS brreg_role_org_idx ON brreg_role_index(orgnr);

CREATE TABLE IF NOT EXISTS search_queries (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  investigation_id uuid NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
  provider text NOT NULL,
  query text NOT NULL,
  query_hash char(64) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(investigation_id, provider, query_hash)
);

CREATE TABLE IF NOT EXISTS reports (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  investigation_id uuid NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
  state text NOT NULL DEFAULT 'DRAFT',
  report_json jsonb NOT NULL,
  html_storage_key text,
  pdf_storage_key text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_log (
  id bigserial PRIMARY KEY,
  investigation_id uuid REFERENCES investigations(id) ON DELETE SET NULL,
  event_type text NOT NULL,
  actor text,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
