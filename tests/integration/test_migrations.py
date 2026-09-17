import json
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


def _database_name(url: str) -> str:
    name = urlsplit(url).path.lstrip("/")
    if not name:
        raise ValueError("TEST_DATABASE_URL must include a database name")
    return name


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


@pytest.mark.asyncio
async def test_migrations_preserve_legacy_data_and_are_idempotent() -> None:
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
            VALUES ('person', '{"name":"Legacy Sentinel"}', 'migration test')
            RETURNING id
            """
        )
        lead_id = await database.fetchval(
            """
            INSERT INTO leads (investigation_id, lead_type, value, reason, status)
            VALUES ($1, 'legacy', '{"sentinel":"preserve-me"}', 'legacy lead', 'OPEN')
            RETURNING id
            """,
            investigation_id,
        )
        await database.close()

        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT,
            env={**os.environ, "DATABASE_URL": _sqlalchemy_url(scratch_url)},
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

        database = await asyncpg.connect(_asyncpg_url(scratch_url))
        lead = await database.fetchrow(
            "SELECT value, status, blocked_reason FROM leads WHERE id = $1", lead_id
        )
        assert lead is not None
        assert json.loads(lead["value"]) == {"sentinel": "preserve-me"}
        assert lead["status"] == "BLOCKED"
        assert lead["blocked_reason"] == "legacy_scope_metadata_required"

        audit = await database.fetchrow(
            """
            SELECT event_type, payload
            FROM audit_log
            WHERE investigation_id = $1 AND event_type = 'SCOPE_MIGRATED'
            """,
            investigation_id,
        )
        assert audit is not None
        assert json.loads(audit["payload"])["scope_modules"] == []

        await database.close()
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT,
            env={**os.environ, "DATABASE_URL": _sqlalchemy_url(scratch_url)},
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

        database = await asyncpg.connect(_asyncpg_url(scratch_url))
        assert (
            await database.fetchval(
                """
                SELECT count(*) FROM audit_log
                WHERE investigation_id = $1 AND event_type = 'SCOPE_MIGRATED'
                """,
                investigation_id,
            )
        ) == 1
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
