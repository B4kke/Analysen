import pytest

from apps.api.app.services.crawler_security import UnsafeUrl, validate_public_http_url


@pytest.mark.asyncio
async def test_localhost_is_blocked() -> None:
    with pytest.raises(UnsafeUrl):
        await validate_public_http_url("http://localhost/admin")
