"""Unit tests for the document fetcher contract (AQ-021 follow-up).

No network access: engine availability is patched off, unsafe URLs are
rejected before any fetch, and raw storage uses an isolated directory.
Redirect SSRF tests use httpx.MockTransport plus a fake
validate_public_http_url (no live DNS): public test hosts are allowed,
private/loopback/link-local hosts and non-http schemes are refused.
"""

import hashlib
from urllib.parse import urlsplit

import httpx
import pytest

from apps.api.app.services import document_fetcher
from apps.api.app.services.crawler_security import UnsafeUrl
from apps.api.app.services.document_fetcher import (
    MAX_REDIRECT_HOPS,
    DocumentFetcher,
    FetchConfig,
)


@pytest.fixture
def isolated_raw_store(monkeypatch, tmp_path):
    from apps.api.app.core import config

    monkeypatch.setenv("RAW_EVIDENCE_DIR", str(tmp_path / "raw"))
    config.get_settings.cache_clear()
    yield tmp_path / "raw"
    config.get_settings.cache_clear()


def _install_fake_validator(monkeypatch) -> list[str]:
    """Install a DNS-free validator; return the list of validated URLs."""
    validated: list[str] = []

    async def fake_validate(url: str) -> None:
        validated.append(url)
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"}:
            raise UnsafeUrl("only http/https are allowed")
        host = (parts.hostname or "").casefold()
        if host in {
            "localhost",
            "127.0.0.1",
            "169.254.169.254",
            "10.0.0.1",
            "0.0.0.0",
        } or host.endswith(".local"):
            raise UnsafeUrl("blocked test-private host")
        return None

    monkeypatch.setattr(document_fetcher, "validate_public_http_url", fake_validate)
    return validated


def _mock_client(handler) -> httpx.AsyncClient:  # type: ignore[no-untyped-def]
    transport = httpx.MockTransport(handler)
    # Intentionally allow auto-follow on the injected client: fetch_raw must
    # still not follow automatically because it passes follow_redirects=False
    # per request and drives redirects manually.
    return httpx.AsyncClient(transport=transport, follow_redirects=True)


@pytest.mark.asyncio
async def test_store_raw_persists_content_not_url(isolated_raw_store) -> None:
    fetcher = DocumentFetcher()
    try:
        url = "https://example.com/article?utm_source=x"
        content = "<html><body>Real fetched bytes</body></html>"
        digest = await fetcher._store_raw(url, content)

        assert digest == hashlib.sha256(content.encode("utf-8")).hexdigest()
        assert digest != hashlib.sha256(url.encode("utf-8")).hexdigest()
        stored = next((isolated_raw_store).rglob(digest))
        assert stored.read_text(encoding="utf-8") == content
    finally:
        await fetcher._client.aclose()


@pytest.mark.asyncio
async def test_fetch_rejects_unsafe_url_before_engines(monkeypatch) -> None:
    fetcher = DocumentFetcher()
    try:
        with pytest.raises(UnsafeUrl):
            await fetcher.fetch("http://localhost:9/internal")
    finally:
        await fetcher._client.aclose()


@pytest.mark.asyncio
async def test_fetch_fails_closed_without_engines(monkeypatch) -> None:
    async def allow_any(url: str) -> None:
        return None

    monkeypatch.setattr(document_fetcher, "validate_public_http_url", allow_any)
    monkeypatch.setattr(document_fetcher, "_TRAFILATURA_AVAILABLE", False)
    monkeypatch.setattr(document_fetcher, "_CRAWL4AI_AVAILABLE", False)
    monkeypatch.setattr(document_fetcher, "_PLAYWRIGHT_AVAILABLE", False)
    fetcher = DocumentFetcher(
        FetchConfig(obey_robots=False),
        client=_mock_client(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text="<html>fixture</html>",
            )
        ),
    )
    try:
        result = await fetcher.fetch("https://example.com/article")
        assert result.content == ""
        assert result.error == "All extraction methods failed"
    finally:
        await fetcher._client.aclose()


def test_default_client_disables_auto_redirects() -> None:
    assert FetchConfig().follow_redirects is False
    assert FetchConfig().max_redirects <= MAX_REDIRECT_HOPS
    assert MAX_REDIRECT_HOPS == 3


@pytest.mark.asyncio
async def test_default_httpx_client_has_follow_redirects_false() -> None:
    fetcher = DocumentFetcher()
    try:
        assert fetcher._client.follow_redirects is False
    finally:
        await fetcher._client.aclose()


@pytest.mark.asyncio
async def test_fetch_raw_follows_public_chain_and_records_final_url(
    monkeypatch,
) -> None:
    validated = _install_fake_validator(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/start":
            # Relative Location exercises urljoin resolution.
            return httpx.Response(302, headers={"location": "/middle"})
        if path == "/middle":
            return httpx.Response(302, headers={"location": "https://example.com/final"})
        if path == "/final":
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text="<html><body>final article body</body></html>",
            )
        return httpx.Response(404, text="not found")

    fetcher = DocumentFetcher(
        FetchConfig(obey_robots=False, rate_limit_per_domain=1000),
        client=_mock_client(handler),
    )
    try:
        result = await fetcher.fetch_raw("https://example.com/start")
        assert result.error is None
        assert "final article body" in result.content
        assert result.final_url == "https://example.com/final"
        assert result.url == "https://example.com/start"
        # Every hop plus the final URL was re-validated.
        assert validated[0] == "https://example.com/start"
        assert "https://example.com/middle" in validated
        assert "https://example.com/final" in validated
    finally:
        await fetcher._client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "private_target",
    ["http://127.0.0.1/", "http://169.254.169.254/"],
)
async def test_fetch_raw_refuses_redirect_to_private_ip(monkeypatch, private_target: str) -> None:
    _install_fake_validator(monkeypatch)
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": private_target})
        return httpx.Response(200, text="must never be fetched")

    fetcher = DocumentFetcher(
        FetchConfig(obey_robots=False, rate_limit_per_domain=1000),
        client=_mock_client(handler),
    )
    try:
        with pytest.raises(UnsafeUrl):
            await fetcher.fetch_raw("https://example.com/start")
        # The private destination was never requested over the transport.
        assert requested == ["https://example.com/start"]
    finally:
        await fetcher._client.aclose()


@pytest.mark.asyncio
async def test_fetch_raw_aborts_redirect_loop(monkeypatch) -> None:
    _install_fake_validator(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/a":
            return httpx.Response(302, headers={"location": "/b"})
        if request.url.path == "/b":
            return httpx.Response(302, headers={"location": "/a"})
        return httpx.Response(404, text="not found")

    fetcher = DocumentFetcher(
        FetchConfig(obey_robots=False, rate_limit_per_domain=1000),
        client=_mock_client(handler),
    )
    try:
        result = await fetcher.fetch_raw("https://example.com/a")
        assert result.content == ""
        assert result.error is not None
        assert "loop" in result.error.lower()
    finally:
        await fetcher._client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_location",
    ["file:///etc/passwd", "javascript:alert(1)", "ftp://example.com/x"],
)
async def test_fetch_raw_refuses_non_http_location_scheme(monkeypatch, bad_location: str) -> None:
    _install_fake_validator(monkeypatch)
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(302, headers={"location": bad_location})

    fetcher = DocumentFetcher(
        FetchConfig(obey_robots=False, rate_limit_per_domain=1000),
        client=_mock_client(handler),
    )
    try:
        with pytest.raises(UnsafeUrl):
            await fetcher.fetch_raw("https://example.com/start")
        assert requested == ["https://example.com/start"]
    finally:
        await fetcher._client.aclose()


@pytest.mark.asyncio
async def test_fetch_raw_aborts_over_limit_chain(monkeypatch) -> None:
    _install_fake_validator(monkeypatch)
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        # Chain /r0 -> /r1 -> /r2 -> /r3 -> /r4 -> 200 exceeds 3 hops.
        if request.url.path.startswith("/r"):
            idx = int(request.url.path[2:])
            if idx < 4:
                return httpx.Response(302, headers={"location": f"/r{idx + 1}"})
            return httpx.Response(200, text="too deep, must not be reached")
        return httpx.Response(404, text="not found")

    fetcher = DocumentFetcher(
        FetchConfig(obey_robots=False, rate_limit_per_domain=1000),
        client=_mock_client(handler),
    )
    try:
        result = await fetcher.fetch_raw("https://example.com/r0")
        assert result.content == ""
        assert result.error is not None
        assert "too many redirects" in result.error.lower()
        # Budget enforced: the tail of the chain was never requested.
        assert "/r4" not in requested
        assert len(requested) == MAX_REDIRECT_HOPS + 1
    finally:
        await fetcher._client.aclose()


@pytest.mark.asyncio
async def test_public_fetch_uses_guarded_raw_bytes_before_extraction(
    monkeypatch, isolated_raw_store
) -> None:
    _install_fake_validator(monkeypatch)
    source = b"<html><body>original bytes for provenance</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=source)

    def extract(payload: str, **_kwargs: object) -> str:
        assert payload == source.decode()
        return "A sufficiently long extracted article body " * 4

    monkeypatch.setattr(document_fetcher, "_TRAFILATURA_AVAILABLE", True)
    monkeypatch.setattr(
        document_fetcher,
        "trafilatura",
        type("FakeTrafilatura", (), {"extract": extract}),
    )
    fetcher = DocumentFetcher(
        config=FetchConfig(obey_robots=False, rate_limit_per_domain=100),
        client=_mock_client(handler),
    )
    try:
        result = await fetcher.fetch("https://example.com/article")
        assert result.error is None
        assert result.metadata["raw_sha256"] == hashlib.sha256(source).hexdigest()
        stored = next(isolated_raw_store.rglob(result.metadata["raw_sha256"]))
        assert stored.read_bytes() == source
    finally:
        await fetcher._client.aclose()
