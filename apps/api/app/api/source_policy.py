"""Source switches shared by direct HTTP API paths."""

from fastapi import HTTPException

from apps.api.app.core.config import get_settings
from apps.api.app.services.source_router import named_source_enabled


def require_enabled_source(source_id: str) -> None:
    _, sources, _ = get_settings().validate_yaml_configs()
    if not named_source_enabled(source_id, sources):
        raise HTTPException(status_code=503, detail=f"Source disabled: {source_id}")
