ALTER TABLE investigations
  ADD COLUMN scope_modules text[] NOT NULL DEFAULT '{}',
  ADD COLUMN expansion_policy text NOT NULL DEFAULT 'CONTEXT_ONLY'
    CHECK (expansion_policy IN ('CONTEXT_ONLY','DIRECT_RELATIONS','MATERIAL_RELATIONS')),
  ADD COLUMN max_relation_depth smallint NOT NULL DEFAULT 0
    CHECK (max_relation_depth BETWEEN 0 AND 3),
  ADD CONSTRAINT valid_scope_modules CHECK (scope_modules <@ ARRAY[
    'WEB_MEDIA','BUSINESS_ROLES','COMPANY_NETWORK','FINANCIALS','ANNOUNCEMENTS_STATUS',
    'HISTORICAL_WEB','DOMAINS_DIGITAL','PUBLIC_PROFILES','SANCTIONS']::text[]);

CREATE TABLE investigation_modules (
  investigation_id uuid NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
  module text NOT NULL CHECK (module IN (
    'WEB_MEDIA','BUSINESS_ROLES','COMPANY_NETWORK','FINANCIALS','ANNOUNCEMENTS_STATUS',
    'HISTORICAL_WEB','DOMAINS_DIGITAL','PUBLIC_PROFILES','SANCTIONS')),
  enabled boolean NOT NULL DEFAULT false,
  status text NOT NULL DEFAULT 'NOT_STARTED'
    CHECK (status IN ('NOT_STARTED','IN_PROGRESS','COMPLETE','PARTIAL','BLOCKED')),
  coverage jsonb NOT NULL DEFAULT '{}'::jsonb,
  stop_reason text,
  started_at timestamptz,
  completed_at timestamptz,
  PRIMARY KEY (investigation_id, module)
);

INSERT INTO investigation_modules (investigation_id, module)
SELECT i.id, m.module FROM investigations i CROSS JOIN unnest(ARRAY[
    'WEB_MEDIA','BUSINESS_ROLES','COMPANY_NETWORK','FINANCIALS','ANNOUNCEMENTS_STATUS',
    'HISTORICAL_WEB','DOMAINS_DIGITAL','PUBLIC_PROFILES','SANCTIONS']) AS m(module);

ALTER TABLE investigation_entities
  ADD COLUMN relation_depth smallint NOT NULL DEFAULT 0 CHECK (relation_depth BETWEEN 0 AND 3),
  ADD COLUMN expansion_state text NOT NULL DEFAULT 'CONTEXT_ONLY'
    CHECK (expansion_state IN ('TARGET','MATERIAL','CONTEXT_ONLY','BLOCKED','RESEARCHED')),
  ADD COLUMN material_reason text;

ALTER TABLE leads
  ADD COLUMN scope_area text,
  ADD COLUMN trigger_type text CHECK (trigger_type IN (
    'IDENTITY_AMBIGUITY','NEW_VERIFIED_ALIAS','MATERIAL_RELATION','WEAK_SOURCE_ONLY',
    'CONTRADICTION','TEMPORAL_GAP','FINANCIAL_ANOMALY','DOCUMENT_QUALITY',
    'DOMAIN_RELEVANCE','MEDIA_CORROBORATION','SANCTIONS_CANDIDATE')),
  ADD COLUMN information_need text,
  ADD COLUMN relation_depth smallint NOT NULL DEFAULT 0 CHECK (relation_depth BETWEEN 0 AND 3),
  ADD COLUMN blocked_reason text,
  ADD FOREIGN KEY (investigation_id, scope_area)
    REFERENCES investigation_modules(investigation_id, module) ON DELETE CASCADE,
  ADD UNIQUE (investigation_id, id),
  ALTER COLUMN status SET DEFAULT 'PENDING';

UPDATE leads SET blocked_reason = 'legacy_scope_metadata_required', status = 'BLOCKED'
WHERE status IN ('OPEN', 'PENDING', 'RUNNING');

ALTER TABLE leads ADD CONSTRAINT executable_lead_metadata CHECK (
  status NOT IN ('PENDING', 'RUNNING') OR (
    scope_area IS NOT NULL AND trigger_type IS NOT NULL
    AND information_need IS NOT NULL AND length(trim(information_need)) > 0
    AND length(trim(reason)) > 0 AND priority BETWEEN 0 AND 1 AND depth >= 0
  )
);

ALTER TABLE search_queries
  ADD COLUMN originating_lead_id uuid,
  ADD COLUMN scope_area text,
  ADD COLUMN query_class text CHECK (query_class IN (
    'IDENTIFIER_EXACT','ENTITY_ALIAS_EXACT','PERSON_COMPANY_RELATION','TEMPORAL',
    'CONTRADICTION','DOMAIN','SOURCE_CONSTRAINED','MEDIA_CORROBORATION','DISCOVERY_BROAD')),
  ADD COLUMN information_need text,
  ADD COLUMN reason text,
  ADD FOREIGN KEY (investigation_id, originating_lead_id)
    REFERENCES leads(investigation_id, id),
  ADD FOREIGN KEY (investigation_id, scope_area)
    REFERENCES investigation_modules(investigation_id, module);

INSERT INTO audit_log (investigation_id, event_type, actor, payload)
SELECT id, 'SCOPE_MIGRATED', 'migration:0002_scope',
  '{"reason":"Legacy investigation requires explicit scope selection","scope_modules":[]}'::jsonb
FROM investigations;
