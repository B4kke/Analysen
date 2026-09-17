from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from apps.api.app.api.routes.brreg import router as brreg_router
from apps.api.app.api.routes.brreg_relationships import router as brreg_relationships_router
from apps.api.app.api.routes.investigations import router as investigations_router
from apps.api.app.core.config import get_settings
from apps.api.app.core.database import database_ready, dispose_database


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await dispose_database()


app = FastAPI(title="Analysen API", version="0.1.0", lifespan=lifespan)
app.include_router(investigations_router)
app.include_router(brreg_router)
app.include_router(brreg_relationships_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> dict[str, str]:
    if await database_ready():
        return {"status": "ready", "database": "ok"}
    return {"status": "degraded", "database": "unavailable"}


@app.get("/api/v1/models")
async def models() -> dict:
    settings = get_settings()
    return settings.load_yaml(settings.model_config_path)


@app.get("/api/v1/sources")
async def sources() -> dict:
    settings = get_settings()
    return settings.load_yaml(settings.source_config_path)


@app.get("/api/v1/policies")
async def policies() -> dict:
    settings = get_settings()
    return settings.load_yaml(settings.policy_config_path)
