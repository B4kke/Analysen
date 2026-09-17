from apps.api.app.services.policy import check_inference_category


def test_sensitive_inference_is_blocked() -> None:
    decision = check_inference_category("religion")
    assert decision.allowed is False


def test_normal_company_attribute_is_allowed() -> None:
    assert check_inference_category("company_role").allowed is True
