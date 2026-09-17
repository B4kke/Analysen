from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from apps.api.app.core.config_models import ModelsConfig, PoliciesConfig, SourcesConfig


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    nim_api_key: str = ""
    nim_base_url: str = "https://integrate.api.nvidia.com/v1"
    database_url: str = "postgresql+asyncpg://analysen:analysen@localhost:5432/analysen"
    redis_url: str = "redis://localhost:6379/0"
    searxng_base_url: str = "http://localhost:8080"
    raw_evidence_dir: Path = Path("./data/raw")
    model_config_path: Path = Path("./config/models.yaml")
    source_config_path: Path = Path("./config/sources.yaml")
    policy_config_path: Path = Path("./config/policies.yaml")
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173"
    readiness_timeout_seconds: float = Field(default=2.0, gt=0, le=10)
    expected_schema_revision: str = "0002_scope"

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, value: str) -> str:
        origins = [origin.strip() for origin in value.split(",") if origin.strip()]
        if not origins:
            raise ValueError("CORS must explicitly list local origins")
        for origin in origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme != "http"
                or parsed.hostname not in {"localhost", "127.0.0.1"}
                or parsed.username
                or parsed.password
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("only explicit localhost CORS origins are allowed")
        return ",".join(origins)

    @property
    def cors_origin_list(self) -> list[str]:
        return self.cors_origins.split(",")

    @staticmethod
    def load_yaml(path: Path) -> dict:
        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}

    def validate_yaml_configs(self) -> tuple[ModelsConfig, SourcesConfig, PoliciesConfig]:
        """Validate all runtime YAML before serving requests; errors fail startup."""
        models = ModelsConfig.model_validate(self.load_yaml(self.model_config_path))
        sources = SourcesConfig.model_validate(self.load_yaml(self.source_config_path))
        policies = PoliciesConfig.model_validate(self.load_yaml(self.policy_config_path))
        return models, sources, policies


@lru_cache
def get_settings() -> Settings:
    return Settings()
