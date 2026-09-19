"""Migration 0005 legacy-upgrade test (AQ-030).

A claim written with the old subject-free fingerprint formula must migrate
to the subject-scoped formula without losing its id or evidence links, and
a repeated upgrade must be a safe no-op. Opt-in: requires TEST_DATABASE_URL
(with CREATEDB).
"""

import hashlib
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

import asyncpg
import pytest

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    pytest.skip(
        "TEST_DATABASE_URL is required for migration integration tests", allow_module_level=True
    )

ROOT = Path(__file__).resolve().parents[2]


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


def _upgrade(scratch_url: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": _sqlalchemy_url(scratch_url)},
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def _old_fingerprint(investigation_id: UUID, predicate: str, value: dict) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{investigation_id}:{predicate}:{canonical}".encode()).hexdigest()


def _new_fingerprint(
    investigation_id: UUID, subject: UUID | None, predicate: str, value: dict
) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    subject_key = str(subject) if subject is not None else ""
    return hashlib.sha256(
        f"{investigation_id}:{subject_key}:{predicate}:{canonical}".encode()
    ).hexdigest()


@pytest.mark.asyncio
async def test_0005_rescopes_legacy_fingerprints_without_losing_links() -> None:
    admin_url = _replace_database(TEST_DATABASE_URL, "postgres")
    scratch = f"analysen_migration_{secrets.token_hex(8)}"
    admin = await asyncpg.connect(_asyncpg_url(admin_url))
    try:
        await admin.execute(f'CREATE DATABASE "{scratch}"')
    finally:
        await admin.close()

    scratch_url = _replace_database(TEST_DATABASE_URL, scratch)
    database = await asyncpg.connect(_asyncpg_url(scratch_url))
    try:
        baseline_sql = (ROOT / "db/migrations/sql/0001_baseline.sql").read_text(encoding="utf-8")
        await database.execute(baseline_sql)
        investigation_id = await database.fetchval(
            """
            INSERT INTO investigations (target_type, target_input, purpose)
            VALUES ('company', '{"name":"Legacy Fingerprint AS"}', 'migration test')
            RETURNING id
            """
        )
        entity_id = await database.fetchval(
            """
            INSERT INTO entities (schema, canonical_name, attributes)
            VALUES ('Company', 'Legacy Fingerprint AS', '{}')
            RETURNING id
            """
        )
        document_id = await database.fetchval(
            """
            INSERT INTO documents (original_url, sha256)
            VALUES ('https://example.invalid/legacy',
                'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc')
            RETURNING id
            """
        )
        evidence_id = await database.fetchval(
            """
            INSERT INTO evidence (document_id, locator_type, locator, excerpt)
            VALUES ($1, 'json_path', '{"section":"navn"}', 'Legacy Fingerprint AS')
            RETURNING id
            """,
            document_id,
        )
        predicate = "company.registered_name"
        value = {"name": "Legacy Fingerprint AS"}
        old_fp = _old_fingerprint(investigation_id, predicate, value)
        claim_id = await database.fetchval(
            """
            INSERT INTO claims (investigation_id, subject_entity_id, predicate, value, fingerprint)
            VALUES ($1, $2, $3, CAST($4 AS jsonb), $5)
            RETURNING id
            """,
            investigation_id,
            entity_id,
            predicate,
            json.dumps(value),
            old_fp,
        )
        await database.execute(
            """
            INSERT INTO claim_evidence (claim_id, evidence_id, relation)
            VALUES ($1, $2, 'supports')
            """,
            claim_id,
            evidence_id,
        )
        await database.close()

        _upgrade(scratch_url)

        database = await asyncpg.connect(_asyncpg_url(scratch_url))
        claim = await database.fetchrow(
            "SELECT id, fingerprint FROM claims WHERE id = $1", claim_id
        )
        assert claim is not None
        assert claim["fingerprint"] == _new_fingerprint(
            investigation_id, entity_id, predicate, value
        )
        assert claim["fingerprint"] != old_fp
        link = await database.fetchrow(
            "SELECT relation FROM claim_evidence WHERE claim_id = $1 AND evidence_id = $2",
            claim_id,
            evidence_id,
        )
        assert link is not None
        assert link["relation"] == "supports"
        revision = await database.fetchval("SELECT version_num FROM alembic_version")
        assert revision == "0010_media_xywh"
        await database.close()

        _upgrade(scratch_url)

        database = await asyncpg.connect(_asyncpg_url(scratch_url))
        assert await database.fetchval("SELECT version_num FROM alembic_version") == (
            "0010_media_xywh"
        )
        assert (
            await database.fetchval("SELECT fingerprint FROM claims WHERE id = $1", claim_id)
        ) == _new_fingerprint(investigation_id, entity_id, predicate, value)
    finally:
        if not database.is_closed():
            await database.close()
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
