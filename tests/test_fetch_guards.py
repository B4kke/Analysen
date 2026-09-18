import asyncio
import hashlib
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from apps.api.app.core import config
from apps.api.app.services import document_fetcher
from apps.api.app.services.document_fetcher import DocumentFetcher, FetchConfig
from apps.api.app.services.raw_store import store_raw_bytes


@pytest.fixture
def guards(monkeypatch, tmp_path):
    async def validate(url):
        return None

    monkeypatch.setattr(document_fetcher, "validate_public_http_url", validate)
    monkeypatch.setenv("RAW_EVIDENCE_DIR", str(tmp_path))
    config.get_settings.cache_clear()
    yield tmp_path
    config.get_settings.cache_clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("robots_status", [401, 403, 500, 503])
async def test_public_fetch_does_not_fetch_page_when_robots_unavailable(guards, robots_status):
    requested = []

    def handle(request):
        requested.append(request.url.path)
        return httpx.Response(robots_status)

    async with DocumentFetcher(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handle))
    ) as f:
        result = await f.fetch("https://research.example/article")
    assert result.error and "robots" in result.error
    assert requested == ["/robots.txt"]


@pytest.mark.asyncio
async def test_redirect_destination_gets_its_own_robots_gate(guards):
    requested = []

    def handle(request):
        requested.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
        return httpx.Response(302, headers={"location": "https://other.example/private"})

    async with DocumentFetcher(
        FetchConfig(rate_limit_per_domain=1000),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    ) as f:
        result = await f.fetch_raw("https://research.example/start")
    assert result.error and "disallows" in result.error
    assert "https://other.example/robots.txt" in requested
    assert "https://other.example/private" not in requested


@pytest.mark.asyncio
async def test_stream_is_aborted_before_entire_oversized_body_is_buffered(guards):
    reads = []

    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            for i in range(100):
                reads.append(i)
                yield b"x" * 8

    async with DocumentFetcher(
        FetchConfig(obey_robots=False, max_content_length=16),
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, stream=Chunks()),
            )
        ),
    ) as f:
        result = await f.fetch_raw("https://research.example/article")
    assert result.error and "max_content_length" in result.error
    assert reads == [0, 1, 2]
    assert list(guards.glob("sha256/*/*/*")) == []


@pytest.mark.asyncio
async def test_concurrency_slot_covers_streaming_response(guards):
    entered = asyncio.Event()
    release = asyncio.Event()
    requests = []

    class BlockingStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            entered.set()
            await release.wait()
            yield b"body"

    def handle(request):
        requests.append(request.url.path)
        return httpx.Response(200, stream=BlockingStream())

    async with DocumentFetcher(
        FetchConfig(obey_robots=False, max_concurrency_per_domain=1, rate_limit_per_domain=1000),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    ) as f:
        first = asyncio.create_task(f.fetch_raw("https://research.example/one"))
        await entered.wait()
        second = asyncio.create_task(f.fetch_raw("https://research.example/two"))
        await asyncio.sleep(0)
        assert requests == ["/one"]
        release.set()
        results = await asyncio.gather(first, second)
    assert all(not result.error for result in results)
    assert requests == ["/one", "/two"]


def test_immutable_store_handles_concurrent_writers_and_detects_corruption(guards):
    payload = b"Original immutable response"
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(store_raw_bytes, [payload] * 20))
    assert len(set(results)) == 1
    digest, key = results[0]
    assert digest == hashlib.sha256(payload).hexdigest()
    assert (guards / key).read_bytes() == payload
    assert list(guards.rglob("*.tmp")) == []
    (guards / key).write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="integrity"):
        store_raw_bytes(payload)
