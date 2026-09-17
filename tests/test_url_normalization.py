from apps.api.app.services.url_normalization import canonicalize_url


def test_tracking_parameters_are_removed() -> None:
    value = canonicalize_url("HTTPS://Example.COM/page?utm_source=x&a=1#fragment")
    assert value == "https://example.com/page?a=1"
