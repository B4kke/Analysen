"""Research runtime smoke tests for the built research image.

These tests replace only the external HTTP/DNS boundary with an explicit
fixture transport and validator. The extraction libraries and Chromium remain
real runtime dependencies. No database or application server is involved.
"""

import hashlib
import json
from urllib.parse import urlsplit

import httpx
import pytest

from apps.api.app.core import config
from apps.api.app.services import document_fetcher
from apps.api.app.services.crawler_security import UnsafeUrl
from apps.api.app.services.document_fetcher import DocumentFetcher, FetchConfig

FIXTURE_HOST = "fixture.test"
PAGE_URL = f"https://{FIXTURE_HOST}/page"


def _validator(monkeypatch):
    async def validate(url: str) -> None:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname != FIXTURE_HOST:
            raise UnsafeUrl(f"fixture policy rejects destination: {url}")

    monkeypatch.setattr(document_fetcher, "validate_public_http_url", validate)


def _client(handler):  # type: ignore[no-untyped-def]
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False)


def _page_html(*, private_script: bool = False) -> bytes:
    resource = "https://127.0.0.1/private.js" if private_script else "/resource.js"
    return f"""<!doctype html>
<html><body><main id="output">initial</main>
<script src="{resource}"></script>
</body></html>""".encode()


@pytest.fixture
def raw_store(monkeypatch, tmp_path):
    directory = tmp_path / "raw"
    monkeypatch.setenv("RAW_EVIDENCE_DIR", str(directory))
    config.get_settings.cache_clear()
    yield directory
    config.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_real_trafilatura_fallback_persists_raw_snapshot(raw_store, monkeypatch):
    if document_fetcher.trafilatura is None:
        pytest.skip("trafilatura is not installed in this runtime")
    _validator(monkeypatch)
    source = (
        b"<html><head><title>Fixture</title></head><body>"
        b"This is a sufficiently long fixture article body for extraction. "
        b"It contains source text that must survive the raw snapshot path."
        b"</body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == PAGE_URL
        return httpx.Response(
            200,
            headers={"content-type": "text/html", "content-length": str(len(source))},
            content=source,
        )

    monkeypatch.setattr(document_fetcher, "_TRAFILATURA_AVAILABLE", True)
    monkeypatch.setattr(document_fetcher, "_CRAWL4AI_AVAILABLE", False)
    monkeypatch.setattr(document_fetcher, "_PLAYWRIGHT_AVAILABLE", False)
    async with DocumentFetcher(
        FetchConfig(obey_robots=False, rate_limit_per_domain=1000), client=_client(handler)
    ) as fetcher:
        result = await fetcher.fetch(PAGE_URL)

    assert result.error is None
    assert result.metadata["extractor"] == "trafilatura"
    digest = hashlib.sha256(source).hexdigest()
    assert result.metadata["raw_sha256"] == digest
    assert result.raw_bytes == source
    assert (raw_store / result.metadata["raw_storage_key"]).read_bytes() == source


@pytest.mark.asyncio
async def test_real_crawl4ai_offline_fallback_uses_original_snapshot(raw_store, monkeypatch):
    if document_fetcher._crawl_markdown is None:
        pytest.skip("Crawl4AI markdown generator is not installed in this runtime")
    _validator(monkeypatch)
    source = (
        b"<html><body><article><h1>Offline fixture</h1>"
        b"<p>Crawl4AI must extract this sufficiently long fixture body without network access.</p>"
        b"</article></body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == PAGE_URL
        return httpx.Response(200, headers={"content-type": "text/html"}, content=source)

    monkeypatch.setattr(document_fetcher, "_TRAFILATURA_AVAILABLE", False)
    monkeypatch.setattr(document_fetcher, "_CRAWL4AI_AVAILABLE", True)
    monkeypatch.setattr(document_fetcher, "_PLAYWRIGHT_AVAILABLE", False)
    async with DocumentFetcher(
        FetchConfig(obey_robots=False, rate_limit_per_domain=1000), client=_client(handler)
    ) as fetcher:
        result = await fetcher.fetch(PAGE_URL)

    assert result.error is None
    assert result.metadata["extractor"] == "crawl4ai"
    assert "Offline fixture" in result.content
    assert result.raw_bytes == source
    assert (raw_store / result.metadata["raw_storage_key"]).read_bytes() == source


@pytest.mark.asyncio
async def test_real_playwright_fallback_renders_guarded_same_host_xhr(raw_store, monkeypatch):
    pytest.importorskip("playwright.async_api")
    _validator(monkeypatch)
    source = _page_html()
    script = (
        b"fetch('/data.json').then(response => response.json()).then(data => "
        b"document.querySelector('#output').textContent = data.message);"
    )
    data = json.dumps({"message": "XHR resource loaded"}).encode()
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.path == "/page":
            return httpx.Response(200, headers={"content-type": "text/html"}, content=source)
        if request.url.path == "/resource.js":
            return httpx.Response(
                200, headers={"content-type": "application/javascript"}, content=script
            )
        if request.url.path == "/data.json":
            return httpx.Response(200, headers={"content-type": "application/json"}, content=data)
        raise AssertionError(f"unexpected fixture request: {request.url}")

    monkeypatch.setattr(document_fetcher, "_TRAFILATURA_AVAILABLE", False)
    monkeypatch.setattr(document_fetcher, "_CRAWL4AI_AVAILABLE", False)
    monkeypatch.setattr(document_fetcher, "_PLAYWRIGHT_AVAILABLE", True)
    async with DocumentFetcher(
        FetchConfig(obey_robots=False, rate_limit_per_domain=1000), client=_client(handler)
    ) as fetcher:
        result = await fetcher.fetch(PAGE_URL)

    assert result.error is None
    assert result.metadata["extractor"] == "playwright"
    assert "XHR resource loaded" in result.content
    assert result.metadata["raw_sha256"] == hashlib.sha256(source).hexdigest()
    assert result.metadata["rendered_sha256"]
    assert result.metadata["rendered_storage_key"].startswith("sha256/")
    resource_urls = {item["final_url"] for item in result.metadata["resources"]}
    assert f"https://{FIXTURE_HOST}/data.json" in resource_urls
    assert f"https://{FIXTURE_HOST}/resource.js" in resource_urls
    assert f"https://{FIXTURE_HOST}/data.json" in requests
    assert (raw_store / result.metadata["raw_storage_key"]).read_bytes() == source


@pytest.mark.asyncio
async def test_playwright_private_resource_is_explicit_policy_failure(raw_store, monkeypatch):
    pytest.importorskip("playwright.async_api")
    _validator(monkeypatch)
    source = _page_html(private_script=True)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/page"
        return httpx.Response(200, headers={"content-type": "text/html"}, content=source)

    monkeypatch.setattr(document_fetcher, "_TRAFILATURA_AVAILABLE", False)
    monkeypatch.setattr(document_fetcher, "_CRAWL4AI_AVAILABLE", False)
    monkeypatch.setattr(document_fetcher, "_PLAYWRIGHT_AVAILABLE", True)
    async with DocumentFetcher(
        FetchConfig(obey_robots=False, rate_limit_per_domain=1000), client=_client(handler)
    ) as fetcher:
        result = await fetcher.fetch(PAGE_URL)

    assert result.error is not None
    assert "playwright" in result.error
    assert "rendered_sha256" not in result.metadata
    assert (raw_store / result.metadata["raw_storage_key"]).read_bytes() == source


@pytest.mark.asyncio
async def test_playwright_resource_robots_deny_is_explicit_failure(raw_store, monkeypatch):
    pytest.importorskip("playwright.async_api")
    _validator(monkeypatch)
    source = _page_html()
    script = b"document.querySelector('#output').textContent = 'should not run';"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /resource.js\n")
        if request.url.path == "/page":
            return httpx.Response(200, headers={"content-type": "text/html"}, content=source)
        if request.url.path == "/resource.js":
            return httpx.Response(
                200, headers={"content-type": "application/javascript"}, content=script
            )
        raise AssertionError(f"unexpected fixture request: {request.url}")

    monkeypatch.setattr(document_fetcher, "_TRAFILATURA_AVAILABLE", False)
    monkeypatch.setattr(document_fetcher, "_CRAWL4AI_AVAILABLE", False)
    monkeypatch.setattr(document_fetcher, "_PLAYWRIGHT_AVAILABLE", True)
    async with DocumentFetcher(
        FetchConfig(rate_limit_per_domain=1000), client=_client(handler)
    ) as fetcher:
        result = await fetcher.fetch(PAGE_URL)

    assert result.error is not None
    assert "playwright" in result.error
    assert "rendered_sha256" not in result.metadata
    assert (raw_store / result.metadata["raw_storage_key"]).read_bytes() == source
