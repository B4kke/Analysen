from fastapi import FastAPI

from apps.api.app.core.config import get_settings

app = FastAPI(title="Analysen API", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


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
