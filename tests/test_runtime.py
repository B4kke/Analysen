from types import SimpleNamespace

import pytest

from apps.api.app.core import database


class _Connection:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def execute(self, _query):
        return None

    async def scalar(self, _query):
        return "0002_scope"


class _Engine:
    def connect(self):
        return _Connection()


@pytest.mark.asyncio
async def test_database_ready_requires_expected_schema(monkeypatch) -> None:
    settings = SimpleNamespace(expected_schema_revision="0002_scope", readiness_timeout_seconds=1)
    monkeypatch.setattr(database, "get_settings", lambda: settings)
    monkeypatch.setattr(database, "get_engine", lambda: _Engine())
    assert await database.database_ready() is True


@pytest.mark.asyncio
async def test_database_ready_fails_for_old_schema(monkeypatch) -> None:
    settings = SimpleNamespace(expected_schema_revision="0002_scope", readiness_timeout_seconds=1)
    monkeypatch.setattr(database, "get_settings", lambda: settings)

    class OldConnection(_Connection):
        async def scalar(self, _query):
            return "0001_baseline"

    class OldEngine(_Engine):
        def connect(self):
            return OldConnection()

    monkeypatch.setattr(database, "get_engine", lambda: OldEngine())
    assert await database.database_ready() is False


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
