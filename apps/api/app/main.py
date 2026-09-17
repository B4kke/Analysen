import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from apps.api.app.api.routes.brreg import router as brreg_router
from apps.api.app.api.routes.brreg_relationships import router as brreg_relationships_router
from apps.api.app.api.routes.investigations import router as investigations_router
from apps.api.app.core.config import get_settings
from apps.api.app.core.database import database_ready, dispose_database, redis_ready


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Configuration errors must prevent the service from accepting traffic.
    get_settings().validate_yaml_configs()
    yield
    await dispose_database()


app = FastAPI(title="Analysen API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Accept", "Content-Type", "Authorization"],
)
app.include_router(investigations_router)
app.include_router(brreg_router)
app.include_router(brreg_relationships_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", response_model=None)
async def ready() -> dict[str, str] | JSONResponse:
    database_ok, redis_ok = await asyncio.gather(database_ready(), redis_ready())
    if database_ok and redis_ok:
        return {"status": "ready", "database": "ok", "redis": "ok"}
    return JSONResponse(
        status_code=503,
        content={
            "status": "unavailable",
            "database": "ok" if database_ok else "unavailable",
            "redis": "ok" if redis_ok else "unavailable",
        },
    )


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
