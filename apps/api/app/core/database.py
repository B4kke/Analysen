import asyncio
from collections.abc import AsyncIterator

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from apps.api.app.core.config import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_recycle=1800,
            # Actors execute asyncio.run repeatedly; pooled asyncpg connections
            # must never be reused across event loops.
            poolclass=NullPool,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def database_ready() -> bool:
    settings = get_settings()
    try:
        async def check() -> None:
            async with get_engine().connect() as connection:
                await connection.execute(text("SELECT 1"))
                revision = await connection.scalar(
                    text("SELECT version_num FROM alembic_version LIMIT 1")
                )
                if revision != settings.expected_schema_revision:
                    raise RuntimeError("database schema is not at expected Alembic head")

        await asyncio.wait_for(check(), timeout=settings.readiness_timeout_seconds)
        return True
    except Exception:
        return False


async def redis_ready() -> bool:
    """Bounded Redis ping with guaranteed client cleanup."""
    settings = get_settings()
    client: Redis | None = None
    try:
        client = Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=settings.readiness_timeout_seconds,
            socket_timeout=settings.readiness_timeout_seconds,
        )
        await asyncio.wait_for(client.ping(), timeout=settings.readiness_timeout_seconds)
        return True
    except Exception:
        return False
    finally:
        if client is not None:
            await client.aclose()


async def dispose_database() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
