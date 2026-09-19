"""AQ-021 policy tests with a local fixture behind an injected transport."""

import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import httpx
import pytest

from apps.api.app.services import document_fetcher
from apps.api.app.services.crawler_security import UnsafeUrl
from apps.api.app.services.document_fetcher import DocumentFetcher, FetchConfig


class _FixtureHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/article")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/private-redirect":
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1/private")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/oversize":
            body = b"x" * 128
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/robots.txt":
            body = b"User-agent: *\nDisallow: /blocked\n"
            self.send_response(200)
        elif self.path == "/robots-403.txt":
            body = b"forbidden"
            self.send_response(403)
        elif self.path == "/blocked":
            body = b"must not be fetched"
            self.send_response(200)
        else:
            body = b"<html><body>Fixture article with enough original bytes.</body></html>"
            if self.path.startswith("/article?nonce="):
                body += self.path.encode("ascii")
            self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return


@pytest.fixture
def fixture_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        thread.join(timeout=2)


class _RewriteFixtureTransport(httpx.AsyncBaseTransport):
    """Injects the local fixture boundary without weakening app URL policy."""

    def __init__(self, port: int):
        self._transport = httpx.AsyncHTTPTransport()
        self._port = port

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.host != "fixture.test":
            raise AssertionError(f"unexpected network destination: {request.url}")
        rewritten = request.url.copy_with(host="127.0.0.1", port=self._port)
        rewritten_request = httpx.Request(
            request.method,
            rewritten,
            headers=request.headers,
            content=request.content,
            extensions=request.extensions,
        )
        return await self._transport.handle_async_request(rewritten_request)

    async def aclose(self) -> None:
        await self._transport.aclose()


@pytest.fixture
def fixture_validator(monkeypatch):
    async def validate(url: str) -> None:
        if not url.startswith("http://fixture.test"):
            raise UnsafeUrl("fixture policy rejects destination")

    monkeypatch.setattr(document_fetcher, "validate_public_http_url", validate)


@pytest.mark.asyncio
async def test_public_fetch_persists_original_bytes_and_hash(
    fixture_server, fixture_validator, monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("RAW_EVIDENCE_DIR", str(tmp_path / "raw"))
    from apps.api.app.core import config

    config.get_settings.cache_clear()
    source = b"<html><body>Fixture article with enough original bytes.</body></html>"
    fake = SimpleNamespace(extract=lambda text, **_: "Extracted fixture article " * 8)
    monkeypatch.setattr(document_fetcher, "trafilatura", fake)
    monkeypatch.setattr(document_fetcher, "_TRAFILATURA_AVAILABLE", True)
    client = httpx.AsyncClient(transport=_RewriteFixtureTransport(fixture_server))
    fetcher = DocumentFetcher(
        FetchConfig(obey_robots=False, rate_limit_per_domain=100), client=client
    )
    try:
        result = await fetcher.fetch("http://fixture.test/article")
        assert result.error is None
        digest = hashlib.sha256(source).hexdigest()
        assert result.metadata["raw_sha256"] == digest
        stored = tmp_path / "raw" / "sha256" / digest[:2] / digest[2:4] / digest
        assert stored.read_bytes() == source
    finally:
        await fetcher.__aexit__(None, None, None)
        config.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_redirect_is_followed_and_private_destination_is_blocked(
    fixture_server, fixture_validator
) -> None:
    transport = _RewriteFixtureTransport(fixture_server)
    fetcher = DocumentFetcher(
        FetchConfig(obey_robots=False), client=httpx.AsyncClient(transport=transport)
    )
    try:
        followed = await fetcher.fetch_raw("http://fixture.test/redirect")
        assert followed.final_url.endswith("/article")
        with pytest.raises(UnsafeUrl):
            await fetcher.fetch_raw("http://fixture.test/private-redirect")
    finally:
        await fetcher.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_content_limit_and_domain_page_budget_are_explicit(
    fixture_server, fixture_validator
) -> None:
    fetcher = DocumentFetcher(
        FetchConfig(obey_robots=False, max_content_length=16, max_pages_per_domain=1),
        client=httpx.AsyncClient(transport=_RewriteFixtureTransport(fixture_server)),
    )
    try:
        oversized = await fetcher.fetch_raw("http://fixture.test/oversize")
        assert oversized.error and "max_content_length" in oversized.error
        budget = await fetcher.fetch_raw("http://fixture.test/article")
        assert budget.error and "page budget" in budget.error
    finally:
        await fetcher.__aexit__(None, None, None)
