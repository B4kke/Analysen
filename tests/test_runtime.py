import pytest

from apps.api.app.core import database
from apps.api.app.core.config import Settings


class _Connection:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def execute(self, _query):
        return None

    async def scalar(self, _query):
        return Settings(_env_file=None).expected_schema_revision


class _Engine:
    def connect(self):
        return _Connection()


@pytest.mark.asyncio
async def test_database_ready_requires_expected_schema(monkeypatch) -> None:
    settings = Settings(_env_file=None)
    monkeypatch.setattr(database, "get_settings", lambda: settings)
    monkeypatch.setattr(database, "get_engine", lambda: _Engine())
    assert await database.database_ready() is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "revision", ["0001_baseline", "0002_scope", "0003_claims_evidence", "unknown"]
)
async def test_database_ready_fails_for_old_or_unknown_schema(monkeypatch, revision) -> None:
    settings = Settings(_env_file=None)
    monkeypatch.setattr(database, "get_settings", lambda: settings)

    class OldConnection(_Connection):
        async def scalar(self, _query):
            return revision

    class OldEngine(_Engine):
        def connect(self):
            return OldConnection()

    monkeypatch.setattr(database, "get_engine", lambda: OldEngine())
    assert await database.database_ready() is False


def test_readiness_default_tracks_packaged_migration_head() -> None:
    from pathlib import Path

    from alembic.script import ScriptDirectory

    root = Path(__file__).resolve().parents[1]
    head = ScriptDirectory(str(root / "db" / "migrations")).get_current_head()
    assert head is not None
    assert Settings(_env_file=None).expected_schema_revision == head


def test_readiness_schema_can_be_explicitly_overridden(monkeypatch) -> None:
    monkeypatch.setenv("EXPECTED_SCHEMA_REVISION", "deployment_override")
    assert Settings(_env_file=None).expected_schema_revision == "deployment_override"


@pytest.mark.asyncio
async def test_http_health_readiness_and_cors(monkeypatch) -> None:
    import httpx

    from apps.api.app import main

    async def available():
        return True

    async def unavailable():
        return False

    monkeypatch.setattr(main, "database_ready", available)
    monkeypatch.setattr(main, "redis_ready", unavailable)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test"
    ) as client:
        assert (await client.get("/health")).status_code == 200
        response = await client.get("/ready")
        assert response.status_code == 503
        assert response.json() == {
            "status": "unavailable", "database": "ok", "redis": "unavailable"
        }
        monkeypatch.setattr(main, "redis_ready", available)
        assert (await client.get("/ready")).status_code == 200
        preflight = await client.options(
            "/api/v1/investigations/anything/scope",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "PATCH",
            },
        )
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == "http://localhost:3000"
