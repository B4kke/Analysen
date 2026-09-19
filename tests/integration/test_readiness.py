"""Readiness checks the schema actually migrated in PostgreSQL (AQ-029)."""

import os

import pytest

from apps.api.app.core import config, database

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL is required for integration tests",
)


@pytest.mark.asyncio
async def test_database_readiness_accepts_packaged_head_and_rejects_mismatch(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.delenv("EXPECTED_SCHEMA_REVISION", raising=False)
    config.get_settings.cache_clear()
    await database.dispose_database()
    try:
        # The coordinator upgrades this isolated database with the packaged chain.
        assert await database.database_ready() is True
        monkeypatch.setenv("EXPECTED_SCHEMA_REVISION", "unknown_schema")
        config.get_settings.cache_clear()
        assert await database.database_ready() is False
    finally:
        await database.dispose_database()
        config.get_settings.cache_clear()
