from functools import lru_cache
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    @staticmethod
    def load_yaml(path: Path) -> dict:
        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}


@lru_cache
def get_settings() -> Settings:
    return Settings()
