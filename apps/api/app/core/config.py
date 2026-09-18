import ipaddress
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from alembic.script import ScriptDirectory
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from apps.api.app.core.config_models import ModelsConfig, PoliciesConfig, SourcesConfig


def _packaged_schema_revision() -> str:
    """Require the schema shipped with this application, including future migrations."""
    migrations = Path(__file__).resolve().parents[4] / "db" / "migrations"
    head = ScriptDirectory(str(migrations)).get_current_head()
    if head is None:
        raise ValueError("the application must ship an Alembic migration head")
    return head


_LAN_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)


def _is_local_origin(hostname: str | None) -> bool:
    """Loopback plus private LAN addresses (RFC1918).

    Loopback is the default. RFC1918 addresses are an explicit opt-in for
    same-network access (e.g. mobile on the home network) via CORS_ORIGINS.
    Public hosts are never allowed: there is no auth (ADR-017).
    """
    if hostname in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        address = ipaddress.ip_address(hostname or "")
    except ValueError:
        return False
    return any(address in network for network in _LAN_NETWORKS)


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
    expected_schema_revision: str = Field(default_factory=_packaged_schema_revision)

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
                or not _is_local_origin(parsed.hostname)
                or parsed.username
                or parsed.password
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("only explicit loopback or LAN CORS origins are allowed")
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
