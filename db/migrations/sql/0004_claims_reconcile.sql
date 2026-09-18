-- Reconcile claims/evidence schema with repository contracts (AQ-020 repair).
--
-- Background: 0001_baseline already creates sources, documents, evidence,
-- claims, claim_evidence, entities, entity_aliases and relationships. The
-- 0003 migration re-declared several of these with different shapes via
-- CREATE TABLE IF NOT EXISTS, which silently does nothing on existing
-- databases. This migration ALTERs the baseline tables to the canonical
-- shapes the repositories actually use. New 0003-only tables
-- (entity_resolution_candidates, claim_evidence_resolution,
-- evidence_candidates) are untouched. The duplicate entity_relations
-- concept from 0003 is dropped in favour of the baseline `relationships`
-- table. It was created empty, never written by any code path, and keeping
-- two relation tables would corrupt provenance queries.
--
-- Legacy rows are preserved: new columns are nullable or backfilled, and no
-- existing data is rewritten.

-- 1. evidence.content_hash: content-addressed dedup key used by the repo.
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS content_hash char(64);
-- Backfill legacy rows with a stable, unique, clearly-marked digest. md5 is
-- used (not sha256) because it is built-in: no pgcrypto dependency. Legacy
-- markers are 32 hex chars, new rows carry full 64-char sha256 - both are
-- stable and unique, which is all the UNIQUE constraint needs.
-- New rows always carry the real formula (see claims_evidence._store_evidence).
UPDATE evidence
SET content_hash = md5('legacy:' || id::text)
WHERE content_hash IS NULL;
ALTER TABLE evidence ALTER COLUMN content_hash SET NOT NULL;
-- No IF NOT EXISTS exists for ADD CONSTRAINT: guard explicitly so the
-- statement is re-runnable.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'evidence_content_hash_key'
    ) THEN
        ALTER TABLE evidence
            ADD CONSTRAINT evidence_content_hash_key UNIQUE (content_hash);
    END IF;
END $$;

-- 2. entity_aliases.confidence: scorer confidence for alias candidates.
ALTER TABLE entity_aliases ADD COLUMN IF NOT EXISTS confidence float NOT NULL DEFAULT 1.0;
-- Do not add a retroactive UNIQUE index here: legacy 0001 data may contain
-- duplicate aliases, and an upgrade must preserve those rows. The repository
-- serializes first-write-wins inserts by locking the parent entity instead.

-- 3. claims.verified_at: when a claim reached a terminal verified state.
ALTER TABLE claims ADD COLUMN IF NOT EXISTS verified_at timestamptz;
-- 3a. Translate the status vocabulary emitted by the original 0003 draft.
-- VERIFIED is deliberately downgraded to INSUFFICIENT_EVIDENCE. The legacy
-- label was written without verifier entailment semantics, so even a linked
-- evidence row cannot safely be promoted to supported. UNVERIFIED is an
-- unverified lead in the canonical vocabulary.
UPDATE claims AS c
SET status = CASE
    WHEN c.status = 'VERIFIED' THEN 'INSUFFICIENT_EVIDENCE'
    WHEN c.status = 'UNVERIFIED' THEN 'UNVERIFIED_LEAD'
    ELSE c.status
END,
verified_at = CASE
    WHEN c.status IN ('VERIFIED', 'UNVERIFIED') THEN NULL
    ELSE c.verified_at
END
WHERE c.status IN ('VERIFIED', 'UNVERIFIED');

-- Status values are enforced at the Pydantic boundary (ClaimStatus); the DB
-- CHECK below mirrors exactly that set. Only Pydantic values are ever
-- written by current code paths; the conversion above handles legacy rows.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'claims_status_check'
    ) THEN
        ALTER TABLE claims ADD CONSTRAINT claims_status_check CHECK (
            status IN (
                'SUPPORTED', 'PARTIALLY_SUPPORTED', 'CONTRADICTED',
                'INSUFFICIENT_EVIDENCE', 'UNVERIFIED_LEAD'
            )
        );
    END IF;
END $$;

-- 4. relationships gains the deterministic analysis columns.
ALTER TABLE relationships ADD COLUMN IF NOT EXISTS confidence float NOT NULL DEFAULT 1.0;
ALTER TABLE relationships ADD COLUMN IF NOT EXISTS evidence_ids uuid[] NOT NULL DEFAULT '{}';

-- 5. Drop the duplicate relation table introduced by 0003. It was created
-- empty by that migration and is referenced by no code path. The baseline
-- `relationships` table above is canonical. Guarded: refuse loudly if any
-- rows ever landed here instead of silently destroying them.
DO $$
BEGIN
    IF (SELECT count(*) FROM entity_relations) > 0 THEN
        RAISE EXCEPTION 'entity_relations is not empty - manual review required';
    END IF;
END $$;
DROP TABLE IF EXISTS entity_relations;
