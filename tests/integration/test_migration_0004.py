"""Migration 0004 legacy-upgrade and fresh-install tests (AQ-020 repair).

Proves a database carrying pre-0004 rows upgrades cleanly: legacy evidence
gets a stable backfilled content_hash, legacy aliases keep working with a
defaulted confidence, claims gain a nullable verified_at, relationships gain
analysis columns, the 0003-only tables survive untouched, and a repeated
upgrade is a safe no-op. A second test proves `alembic upgrade head` builds
the head schema on an empty database.
Opt-in: requires TEST_DATABASE_URL (needs CREATEDB).
"""

import hashlib
import os
import secrets
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    pytest.skip(
        "TEST_DATABASE_URL is required for migration integration tests", allow_module_level=True
    )

ROOT = Path(__file__).resolve().parents[2]

# Tables introduced by 0003 that 0004 must leave untouched.
TABLES_0003_ONLY = (
    "entity_resolution_candidates",
    "claim_evidence_resolution",
    "evidence_candidates",
)


def _replace_database(url: str, database: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database}", parsed.query, parsed.fragment))


def _sqlalchemy_url(url: str) -> str:
    if url.startswith("postgresql+"):
        return url
    return url.replace("postgres://", "postgresql+asyncpg://", 1).replace(
        "postgresql://", "postgresql+asyncpg://", 1
    )


def _asyncpg_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _upgrade(scratch_url: str, revision: str = "head") -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": _sqlalchemy_url(scratch_url)},
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


async def _create_scratch(admin_url: str, scratch: str) -> str:
    admin = await asyncpg.connect(_asyncpg_url(admin_url))
    try:
        await admin.execute(f'CREATE DATABASE "{scratch}"')
    finally:
        await admin.close()
    return _replace_database(TEST_DATABASE_URL, scratch)  # type: ignore[arg-type]


async def _drop_scratch(admin_url: str, scratch: str) -> None:
    admin = await asyncpg.connect(_asyncpg_url(admin_url))
    try:
        await admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            scratch,
        )
        await admin.execute(f'DROP DATABASE IF EXISTS "{scratch}"')
    finally:
        await admin.close()


@pytest.mark.asyncio
async def test_0004_upgrades_legacy_rows_and_is_idempotent() -> None:
    admin_url = _replace_database(TEST_DATABASE_URL, "postgres")  # type: ignore[arg-type]
    scratch = f"analysen_migration_{secrets.token_hex(8)}"
    await _create_scratch(admin_url, scratch)

    scratch_url = _replace_database(TEST_DATABASE_URL, scratch)  # type: ignore[arg-type]
    database = await asyncpg.connect(_asyncpg_url(scratch_url))
    try:
        baseline_sql = (ROOT / "db/migrations/sql/0001_baseline.sql").read_text(encoding="utf-8")
        await database.execute(baseline_sql)
        investigation_id = await database.fetchval(
            """
            INSERT INTO investigations (target_type, target_input, purpose)
            VALUES ('company', '{"name":"Legacy Reconcile AS"}', 'migration test')
            RETURNING id
            """
        )
        source_id = await database.fetchval(
            """
            INSERT INTO sources (id, name, access_class)
            VALUES ('legacy_source', 'Legacy Source', 'OPEN_NO_KEY')
            RETURNING id
            """
        )
        assert source_id == "legacy_source"
        document_id = await database.fetchval(
            """
            INSERT INTO documents (source_id, original_url, sha256)
            VALUES ('legacy_source', 'https://example.invalid/legacy',
                'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')
            RETURNING id
            """
        )
        # Legacy evidence rows: no content_hash column exists yet.
        legacy_sections = ("navn", "organisasjonsnummer")
        for section in legacy_sections:
            await database.execute(
                """
                INSERT INTO evidence (document_id, locator_type, locator, excerpt)
                VALUES ($1, 'json_path', CAST($2 AS jsonb), $3)
                """,
                document_id,
                f'{{"section":"{section}"}}',
                "Legacy Reconcile AS",
            )
        legacy_evidence_id = await database.fetchval(
            "SELECT id FROM evidence WHERE document_id = $1 ORDER BY created_at LIMIT 1",
            document_id,
        )
        entity_id = await database.fetchval(
            """
            INSERT INTO entities (schema, canonical_name, attributes)
            VALUES ('Company', 'Legacy Reconcile AS', '{}')
            RETURNING id
            """
        )
        # Legacy alias row: no confidence column exists yet.
        await database.execute(
            """
            INSERT INTO entity_aliases (entity_id, alias, normalized_alias)
            VALUES ($1, 'Legacy Reconcile AS', 'legacy reconcile as')
            """,
            entity_id,
        )
        # Legacy baseline permits duplicates; 0004 must preserve them rather
        # than fail while trying to add a retroactive unique index.
        await database.execute(
            """
            INSERT INTO entity_aliases (entity_id, alias, normalized_alias)
            VALUES ($1, 'Legacy Reconcile A.S.', 'legacy reconcile as')
            """,
            entity_id,
        )
        # Legacy claim row: no verified_at column exists yet.
        claim_id = await database.fetchval(
            """
            INSERT INTO claims (investigation_id, predicate, value, fingerprint)
            VALUES ($1, 'company.registered_name', '{"name":"Legacy Reconcile AS"}',
                'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb')
            RETURNING id
            """,
            investigation_id,
        )
        verified_legacy_id = await database.fetchval(
            """
            INSERT INTO claims
                (investigation_id, predicate, value, status, fingerprint)
            VALUES ($1, 'company.legacy_verified', '{}', 'VERIFIED', $2)
            RETURNING id
            """,
            investigation_id,
            "f" * 64,
        )
        await database.execute(
            """
            INSERT INTO claim_evidence (claim_id, evidence_id, relation)
            VALUES ($1, $2, 'supports')
            """,
            verified_legacy_id,
            legacy_evidence_id,
        )
        unverified_legacy_id = await database.fetchval(
            """
            INSERT INTO claims
                (investigation_id, predicate, value, status, fingerprint)
            VALUES ($1, 'company.legacy_unverified', '{}', 'UNVERIFIED', $2)
            RETURNING id
            """,
            investigation_id,
            "1" * 64,
        )
        unsupported_verified_id = await database.fetchval(
            """
            INSERT INTO claims
                (investigation_id, predicate, value, status, fingerprint)
            VALUES ($1, 'company.legacy_unproven', '{}', 'VERIFIED', $2)
            RETURNING id
            """,
            investigation_id,
            "2" * 64,
        )
        await database.close()

        # Bring the schema to 0003 so a 0003-only table can hold a row
        # before the 0004 upgrade under test.
        _upgrade(scratch_url, "0003_claims_evidence")

        database = await asyncpg.connect(_asyncpg_url(scratch_url))
        candidate_id = await database.fetchval(
            """
            INSERT INTO evidence_candidates
                (investigation_id, locator_type, locator, excerpt)
            VALUES ($1, 'json_path', CAST('{"section":"navn"}' AS jsonb), 'candidate probe')
            RETURNING id
            """,
            investigation_id,
        )
        await database.close()

        _upgrade(scratch_url)

        database = await asyncpg.connect(_asyncpg_url(scratch_url))
        evidence_rows = await database.fetch(
            "SELECT id, content_hash FROM evidence WHERE document_id = $1", document_id
        )
        assert len(evidence_rows) == len(legacy_sections)
        seen_hashes = set()
        for row in evidence_rows:
            assert row["content_hash"] is not None
            expected = hashlib.md5(f"legacy:{row['id']}".encode()).hexdigest()
            assert row["content_hash"].strip() == expected
            seen_hashes.add(row["content_hash"].strip())
        assert len(seen_hashes) == len(legacy_sections)

        alias = await database.fetchrow(
            "SELECT confidence, normalized_alias FROM entity_aliases WHERE entity_id = $1",
            entity_id,
        )
        assert alias is not None
        assert alias["confidence"] == 1.0
        assert alias["normalized_alias"] == "legacy reconcile as"
        assert await database.fetchval(
            "SELECT count(*) FROM entity_aliases WHERE entity_id = $1", entity_id
        ) == 2

        claim = await database.fetchrow(
            "SELECT verified_at, fingerprint FROM claims WHERE id = $1", claim_id
        )
        assert claim is not None
        assert claim["verified_at"] is None
        assert claim["fingerprint"].startswith("bbbb")
        translated_verified = await database.fetchrow(
            "SELECT status, verified_at FROM claims WHERE id = $1", verified_legacy_id
        )
        assert translated_verified["status"] == "INSUFFICIENT_EVIDENCE"
        assert translated_verified["verified_at"] is None
        translated_unverified = await database.fetchrow(
            "SELECT status, verified_at FROM claims WHERE id = $1", unverified_legacy_id
        )
        assert translated_unverified["status"] == "UNVERIFIED_LEAD"
        assert translated_unverified["verified_at"] is None
        translated_unproven = await database.fetchrow(
            "SELECT status, verified_at FROM claims WHERE id = $1", unsupported_verified_id
        )
        assert translated_unproven["status"] == "INSUFFICIENT_EVIDENCE"
        assert translated_unproven["verified_at"] is None

        relation_columns = await database.fetch(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'relationships'
            """
        )
        assert {"confidence", "evidence_ids"} <= {row["column_name"] for row in relation_columns}

        # 0003-only tables survive the upgrade with their rows intact.
        for table in TABLES_0003_ONLY:
            assert await database.fetchval(
                f"SELECT to_regclass('public.{table}')"
            ) is not None
        candidate = await database.fetchrow(
            "SELECT excerpt FROM evidence_candidates WHERE id = $1", candidate_id
        )
        assert candidate is not None
        assert candidate["excerpt"] == "candidate probe"

        gone = await database.fetchval(
            "SELECT to_regclass('public.entity_relations')"
        )
        assert gone is None

        revision = await database.fetchval("SELECT version_num FROM alembic_version")
        assert revision == "0004_claims_reconcile"
        await database.close()

        # Repeat upgrade is a safe no-op.
        _upgrade(scratch_url)

        database = await asyncpg.connect(_asyncpg_url(scratch_url))
        assert await database.fetchval("SELECT version_num FROM alembic_version") == (
            "0004_claims_reconcile"
        )
        assert (
            await database.fetchval("SELECT count(*) FROM evidence WHERE document_id = $1",
                                    document_id)
        ) == len(legacy_sections)
        assert (
            await database.fetchval(
                "SELECT count(*) FROM evidence_candidates WHERE id = $1", candidate_id
            )
        ) == 1
    finally:
        if not database.is_closed():
            await database.close()
        await _drop_scratch(admin_url, scratch)


@pytest.mark.asyncio
async def test_0004_fresh_database_upgrades_cleanly() -> None:
    """`alembic upgrade head` on an empty database builds the head schema."""
    admin_url = _replace_database(TEST_DATABASE_URL, "postgres")  # type: ignore[arg-type]
    scratch = f"analysen_migration_fresh_{secrets.token_hex(8)}"
    await _create_scratch(admin_url, scratch)

    scratch_url = _replace_database(TEST_DATABASE_URL, scratch)  # type: ignore[arg-type]
    database = await asyncpg.connect(_asyncpg_url(scratch_url))
    try:
        # No baseline.sql: the full chain runs from an empty database.
        await database.close()

        _upgrade(scratch_url)

        database = await asyncpg.connect(_asyncpg_url(scratch_url))
        assert await database.fetchval("SELECT version_num FROM alembic_version") == (
            "0004_claims_reconcile"
        )

        for table in TABLES_0003_ONLY:
            assert await database.fetchval(
                f"SELECT to_regclass('public.{table}')"
            ) is not None
        assert await database.fetchval("SELECT to_regclass('public.entity_relations')") is None

        content_hash_nullable = await database.fetchval(
            """
            SELECT is_nullable FROM information_schema.columns
            WHERE table_name = 'evidence' AND column_name = 'content_hash'
            """
        )
        assert content_hash_nullable == "NO"
        assert await database.fetchval(
            "SELECT count(*) FROM pg_constraint WHERE conname = 'evidence_content_hash_key'"
        ) == 1

        verified_at_nullable = await database.fetchval(
            """
            SELECT is_nullable FROM information_schema.columns
            WHERE table_name = 'claims' AND column_name = 'verified_at'
            """
        )
        assert verified_at_nullable == "YES"

        # Smoke-prove the repository shapes the fresh schema must accept:
        # evidence with content_hash, claim with fingerprint and verified_at.
        investigation_id = await database.fetchval(
            """
            INSERT INTO investigations (target_type, target_input, purpose)
            VALUES ('company', '{"name":"Fresh Head AS"}', 'fresh migration test')
            RETURNING id
            """
        )
        await database.execute(
            """
            INSERT INTO sources (id, name, access_class)
            VALUES ('fresh_source', 'Fresh Source', 'OPEN_NO_KEY')
            ON CONFLICT (id) DO NOTHING
            """
        )
        document_id = await database.fetchval(
            """
            INSERT INTO documents (source_id, original_url, sha256)
            VALUES ('fresh_source', 'https://example.invalid/fresh',
                'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc')
            RETURNING id
            """
        )
        fresh_hash = "d" * 64
        evidence_id = await database.fetchval(
            """
            INSERT INTO evidence (document_id, locator_type, locator, content_hash)
            VALUES ($1, 'json_pointer', CAST('{"pointer":"/"}' AS jsonb), $2)
            RETURNING id
            """,
            document_id,
            fresh_hash,
        )
        stored_hash = await database.fetchval(
            "SELECT content_hash FROM evidence WHERE id = $1", evidence_id
        )
        assert stored_hash.strip() == fresh_hash
        with pytest.raises(asyncpg.UniqueViolationError):
            await database.execute(
                """
                INSERT INTO evidence (document_id, locator_type, locator, content_hash)
                VALUES ($1, 'json_pointer', CAST('{"pointer":"/"}' AS jsonb), $2)
                """,
                document_id,
                fresh_hash,
            )
        claim_id = await database.fetchval(
            """
            INSERT INTO claims
                (investigation_id, predicate, value, status, fingerprint, verified_at)
            VALUES ($1, 'company.registered_name', '{"name":"Fresh Head AS"}',
                'SUPPORTED',
                'eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                now())
            RETURNING id
            """,
            investigation_id,
        )
        claim = await database.fetchrow(
            "SELECT status, verified_at FROM claims WHERE id = $1", claim_id
        )
        assert claim is not None
        assert claim["status"] == "SUPPORTED"
        assert claim["verified_at"] is not None
    finally:
        if not database.is_closed():
            await database.close()
        await _drop_scratch(admin_url, scratch)
