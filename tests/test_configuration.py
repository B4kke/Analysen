import pytest
from pydantic import ValidationError

from apps.api.app.core.config import Settings, get_settings
from apps.api.app.core.config_models import ModelsConfig, PoliciesConfig, SourceConfig


def test_checked_in_yaml_is_typed_and_valid() -> None:
    models, sources, policies = get_settings().validate_yaml_configs()
    assert models.roles
    assert sources.sources["brreg_entities"].enabled is True
    assert policies.privacy.personal_risk_score_allowed is False


def test_safety_policy_fails_closed() -> None:
    raw = get_settings().load_yaml(get_settings().policy_config_path)
    raw["privacy"]["personal_risk_score_allowed"] = True
    with pytest.raises(ValidationError):
        PoliciesConfig.model_validate(raw)


def test_cors_rejects_wildcard_and_remote_origins() -> None:
    with pytest.raises(ValidationError):
        Settings(cors_origins="*")
    with pytest.raises(ValidationError):
        Settings(cors_origins="https://example.invalid")
    with pytest.raises(ValidationError):
        Settings(cors_origins="http://localhost.evil:3000")


def test_restricted_sources_and_incomplete_models_fail_closed() -> None:
    with pytest.raises(ValidationError):
        SourceConfig(enabled=True, access="DISABLED_BY_POLICY")
    raw = get_settings().load_yaml(get_settings().model_config_path)
    raw["roles"].pop("verifier")
    with pytest.raises(ValidationError):
        ModelsConfig.model_validate(raw)
