"""Guarded retrieval, then offline extraction or rendering via the same HTTP boundary.

Original responses are persisted before extraction. Chromium is offline: every
allowed request is fulfilled from guarded HTTP snapshots, never continued to
Chromium's network stack. Crawl4AI supplies offline markdown extraction.
"""

import asyncio
import importlib
import time
import zlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
import structlog

from apps.api.app.services.crawler_security import UnsafeUrl, validate_public_http_url
from apps.api.app.services.raw_store import store_raw_bytes
from apps.api.app.services.safe_http_transport import PublicNetworkTransport
from apps.api.app.services.url_canonicalization import FetchResult

logger = structlog.get_logger()
MAX_REDIRECT_HOPS = 3
_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})


def _optional_module(name: str) -> Any:
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


trafilatura = _optional_module("trafilatura")
_crawl_markdown = _optional_module("crawl4ai.markdown_generation_strategy")
_playwright = _optional_module("playwright.async_api")
async_playwright = _playwright.async_playwright if _playwright else None
_TRAFILATURA_AVAILABLE = trafilatura is not None
_CRAWL4AI_AVAILABLE = _crawl_markdown is not None
_PLAYWRIGHT_AVAILABLE = async_playwright is not None


class FetchPolicyError(RuntimeError):
    """A deterministic crawl policy denied the request."""


@dataclass
class FetchConfig:
    timeout_seconds: float = 30
    max_content_length: int = 10 * 1024 * 1024
    follow_redirects: bool = False  # Auto-follow is never used, including injected clients.
    max_redirects: int = 3
    user_agent: str = "AnalysenBot/1.0 (+https://analysen.no/bot)"
    obey_robots: bool = True
    rate_limit_per_domain: float = 1.0
    max_pages_per_domain: int = 20
    max_concurrency_per_domain: int = 2
    max_requests: int = 100

    def __post_init__(self) -> None:
        if (
            min(
                self.timeout_seconds,
                self.max_content_length,
                self.rate_limit_per_domain,
                self.max_pages_per_domain,
                self.max_concurrency_per_domain,
                self.max_requests,
            )
            <= 0
        ):
            raise ValueError("crawl limits must be positive")
        if self.max_redirects < 0:
            raise ValueError("max_redirects cannot be negative")


class DocumentFetcher:
    def __init__(self, config: FetchConfig | None = None, client: httpx.AsyncClient | None = None):
        self.config = config or FetchConfig()
        self._client = client or httpx.AsyncClient(
            transport=PublicNetworkTransport(),
            trust_env=False,
            timeout=self.config.timeout_seconds,
            follow_redirects=False,
        )
        self._rate_limiter: dict[str, float] = {}
        self._domain_locks: dict[str, asyncio.Lock] = {}
        self._domain_semaphores: dict[str, asyncio.Semaphore] = {}
        self._domain_pages: dict[str, int] = {}
        self._request_count = 0
        self._robots: dict[str, tuple[RobotFileParser | None, str | None]] = {}
        self._robots_locks: dict[str, asyncio.Lock] = {}

    async def __aenter__(self) -> "DocumentFetcher":
        return self

    async def __aexit__(self, *args) -> None:
        await self._client.aclose()

    @asynccontextmanager
    async def _request_slot(self, url: str, *, count_page: bool) -> AsyncIterator[None]:
        host = (urlsplit(url).hostname or "").casefold()
        semaphore = self._domain_semaphores.setdefault(
            host,
            asyncio.Semaphore(self.config.max_concurrency_per_domain),
        )
        async with semaphore:
            lock = self._domain_locks.setdefault(host, asyncio.Lock())
            async with lock:
                if self._request_count >= self.config.max_requests:
                    raise FetchPolicyError("request budget exceeded")
                if (
                    count_page
                    and self._domain_pages.get(host, 0) >= self.config.max_pages_per_domain
                ):
                    raise FetchPolicyError("page budget exceeded")
                delay = 1.0 / self.config.rate_limit_per_domain - (
                    time.monotonic() - self._rate_limiter.get(host, 0.0)
                )
                if delay > 0:
                    await asyncio.sleep(delay)
                # No await between the global check and increment: independent hosts
                # cannot overspend the request budget while waiting for domain delay.
                if self._request_count >= self.config.max_requests:
                    raise FetchPolicyError("request budget exceeded")
                self._request_count += 1
                if count_page:
                    self._domain_pages[host] = self._domain_pages.get(host, 0) + 1
                self._rate_limiter[host] = time.monotonic()
            yield

    def _failure(
        self,
        url: str,
        final_url: str,
        reason: str,
        status: int = 0,
        content_type: str | None = None,
        **metadata: Any,
    ) -> FetchResult:
        logger.info("document_fetch_failed", reason=reason.split(":", 1)[0], status=status)
        return FetchResult(url, final_url, "", content_type, status, metadata, reason)

    async def fetch_raw(self, url: str, *, _robots_document: bool = False) -> FetchResult:
        """Retrieve bounded original bytes with policy applied to every redirect hop.

        The private flag is used only to retrieve robots policy itself. Even that
        path uses pinned public destinations, rate/concurrency and stream limits.
        """
        visited: set[str] = set()
        current = url
        max_hops = min(MAX_REDIRECT_HOPS, self.config.max_redirects)
        for hop in range(max_hops + 1):
            await validate_public_http_url(current)
            if current in visited:
                return self._failure(url, current, "redirect: loop detected")
            visited.add(current)
            if not _robots_document:
                robots_error = await self._check_robots(current)
                if robots_error:
                    return self._failure(url, current, robots_error)
            try:
                async with (
                    asyncio.timeout(self.config.timeout_seconds),
                    self._request_slot(current, count_page=not _robots_document),
                    self._client.stream(
                        "GET",
                        current,
                        follow_redirects=False,
                        headers={
                            "User-Agent": self.config.user_agent,
                            "Accept-Encoding": "identity",
                        },
                    ) as response,
                ):
                    status = response.status_code
                    content_type = response.headers.get("content-type")
                    if status in _REDIRECT_STATUS_CODES:
                        location = response.headers.get("location", "").strip()
                        if not location:
                            return self._failure(url, current, "redirect: missing Location", status)
                        next_url = urljoin(current, location)
                        await validate_public_http_url(next_url)
                        if hop >= max_hops:
                            return self._failure(
                                url, current, "redirect: too many redirects", status
                            )
                        current = next_url
                        continue
                    if not 200 <= status < 300:
                        return self._failure(
                            url, current, "http: unavailable", status, content_type
                        )
                    final_url = str(response.url)
                    await validate_public_http_url(final_url)
                    length = response.headers.get("content-length", "")
                    if length.isdigit() and int(length) > self.config.max_content_length:
                        return self._failure(
                            url,
                            final_url,
                            "size: exceeds max_content_length",
                            status,
                            content_type,
                        )
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in self._body_chunks(response):
                        size += len(chunk)
                        if size > self.config.max_content_length:
                            return self._failure(
                                url,
                                final_url,
                                "size: exceeds max_content_length",
                                status,
                                content_type,
                            )
                        chunks.append(chunk)
                    body = b"".join(chunks)
                    fetched_at = datetime.now(UTC)
                    digest, key = store_raw_bytes(body)
                    metadata = {
                        "source_url": url,
                        "final_url": final_url,
                        "hops": hop,
                        "raw_sha256": digest,
                        "raw_storage_key": key,
                        "fetched_at": fetched_at.isoformat(),
                        "extractor": "httpx",
                        "content_encoding": response.headers.get("content-encoding", ""),
                    }
                    decoded = self._decode_body(body, metadata["content_encoding"])
                    text = httpx.Response(
                        200,
                        content=decoded,
                        headers={"content-type": content_type or ""},
                    ).text
                    return FetchResult(
                        url, final_url, text, content_type, status, metadata,
                        raw_bytes=body, fetched_at=fetched_at
                    )
            except UnsafeUrl:
                raise
            except httpx.InvalidURL as exc:
                raise UnsafeUrl("invalid redirect URL") from exc
            except FetchPolicyError as exc:
                return self._failure(url, current, f"policy: {exc}")
            except (httpx.HTTPError, TimeoutError, ValueError, zlib.error) as exc:
                return self._failure(url, current, f"fetch: {type(exc).__name__}")
        return self._failure(url, current, "redirect: too many redirects")

    async def _body_chunks(self, response: httpx.Response) -> AsyncIterator[bytes]:
        # MockTransport / explicitly buffered injected responses are already read;
        # real streamed transport responses are consumed with an incremental cap.
        if response.is_stream_consumed:
            yield response.content
        else:
            async for chunk in response.aiter_raw():
                yield chunk

    def _decode_body(self, body: bytes, encoding: str) -> bytes:
        if not encoding or encoding == "identity":
            return body
        if encoding not in {"gzip", "deflate"}:
            raise ValueError("unsupported content encoding")
        decoder = zlib.decompressobj(31 if encoding == "gzip" else 15)
        decoded = decoder.decompress(body, self.config.max_content_length + 1)
        if len(decoded) > self.config.max_content_length or decoder.unconsumed_tail:
            raise FetchPolicyError("decoded content exceeds max_content_length")
        if not decoder.eof:
            raise ValueError("truncated encoded response")
        return decoded

    async def _check_robots(self, url: str) -> str | None:
        if not self.config.obey_robots:
            return None
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        lock = self._robots_locks.setdefault(origin, asyncio.Lock())
        parser: RobotFileParser | None
        async with lock:
            if origin not in self._robots:
                try:
                    result = await self.fetch_raw(f"{origin}/robots.txt", _robots_document=True)
                    if result.status_code == 404:
                        policy: tuple[RobotFileParser | None, str | None] = (None, None)
                    elif result.error or result.status_code != 200:
                        policy = (None, "robots: unavailable or access denied")
                    else:
                        parser = RobotFileParser()
                        parser.set_url(f"{origin}/robots.txt")
                        parser.parse(result.content.splitlines())
                        policy = (parser, None)
                    self._robots[origin] = policy
                except UnsafeUrl:
                    self._robots[origin] = (None, "robots: unsafe policy destination")
            parser, error = self._robots[origin]
        if error:
            return error
        if parser is not None and not parser.can_fetch(self.config.user_agent, url):
            return "robots: disallows fetching this URL"
        # Honour crawl-delay / request-rate if the server asks for a lower rate.
        if parser is not None:
            rate = parser.request_rate(self.config.user_agent)
            delay = float(parser.crawl_delay(self.config.user_agent) or 0)
            if rate and rate.requests > 0:
                delay = max(delay, rate.seconds / rate.requests)
            if delay:
                host = (parts.hostname or "").casefold()
                self._rate_limiter[host] = max(
                    self._rate_limiter.get(host, 0),
                    time.monotonic() + delay - 1 / self.config.rate_limit_per_domain,
                )
        return None

    async def fetch(self, url: str) -> FetchResult:
        raw = await self.fetch_raw(url)
        if raw.error:
            return raw
        mime = (raw.content_type or "").split(";", 1)[0].lower()
        if mime in {"text/plain", "application/json"}:
            return raw
        if _TRAFILATURA_AVAILABLE:
            extracted = await self._extract_trafilatura(raw)
            if not extracted.error:
                return extracted
        if _CRAWL4AI_AVAILABLE:
            extracted = await self._extract_crawl4ai(raw)
            if not extracted.error:
                return extracted
        if _PLAYWRIGHT_AVAILABLE:
            return await self._extract_playwright(raw)
        return replace(raw, content="", error="All extraction methods failed")

    async def _extract_trafilatura(self, raw: FetchResult) -> FetchResult:
        try:
            content = await asyncio.to_thread(
                trafilatura.extract,
                raw.content,
                include_comments=False,
                include_tables=True,
                include_formatting=False,
                output_format="txt",
            )
            if not content or len(content.strip()) < 50:
                raise ValueError("insufficient extracted content")
            return replace(
                raw, content=content.strip(), metadata={**raw.metadata, "extractor": "trafilatura"}
            )
        except Exception as exc:
            return replace(raw, content="", error=f"trafilatura: {type(exc).__name__}")

    async def _extract_crawl4ai(self, raw: FetchResult) -> FetchResult:
        try:
            generator = _crawl_markdown.DefaultMarkdownGenerator()
            result = await asyncio.to_thread(
                generator.generate_markdown,
                raw.content,
                base_url=raw.final_url,
                citations=False,
            )
            content = result.raw_markdown
            if not content or len(content.strip()) < 50:
                raise ValueError("insufficient extracted content")
            return replace(
                raw, content=content.strip(), metadata={**raw.metadata, "extractor": "crawl4ai"}
            )
        except Exception as exc:
            return replace(raw, content="", error=f"crawl4ai: {type(exc).__name__}")

    async def _extract_playwright(self, raw: FetchResult) -> FetchResult:
        if async_playwright is None:
            return replace(raw, content="", error="playwright: unavailable")
        cache: dict[str, FetchResult] = {raw.final_url: raw}
        errors: list[str] = []
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                try:
                    context = await browser.new_context(
                        user_agent=self.config.user_agent,
                        service_workers="block",
                        offline=True,
                    )

                    async def block_socket(socket: Any) -> None:
                        await socket.close()

                    await context.route_web_socket("**/*", block_socket)

                    async def fulfill(route: Any) -> None:
                        request = route.request
                        if request.method not in {"GET", "HEAD"} or request.resource_type not in {
                            "document",
                            "script",
                            "stylesheet",
                            "xhr",
                            "fetch",
                        }:
                            await route.abort("blockedbyclient")
                            return
                        try:
                            result = cache.get(request.url)
                            if result is None:
                                result = await self.fetch_raw(request.url)
                                if result.error:
                                    raise FetchPolicyError(result.error)
                                cache[request.url] = result
                                cache[result.final_url] = result
                            if request.url != result.final_url:
                                await route.fulfill(
                                    status=302, headers={"location": result.final_url}
                                )
                            else:
                                await route.fulfill(
                                    status=result.status_code,
                                    content_type=(result.content_type or "text/html").split(";")[0]
                                    + "; charset=utf-8",
                                    body=result.content.encode("utf-8"),
                                )
                        except Exception as exc:
                            errors.append(type(exc).__name__)
                            await route.abort("blockedbyclient")

                    await context.route("**/*", fulfill)
                    page = await context.new_page()
                    await page.goto(
                        raw.final_url,
                        wait_until="networkidle",
                        timeout=self.config.timeout_seconds * 1000,
                    )
                    await validate_public_http_url(page.url)
                    if errors:
                        raise FetchPolicyError(
                            "rendered document has blocked/unavailable resources"
                        )
                    main = cache.get(page.url)
                    if main is None:
                        raise FetchPolicyError("unretrieved final navigation")
                    rendered = await page.content()
                    if len(rendered.encode()) > self.config.max_content_length:
                        raise FetchPolicyError("rendered content exceeds max_content_length")
                    content = await page.locator("body").inner_text()
                    if not content.strip():
                        raise ValueError("empty rendered document")
                    derived_hash, derived_key = store_raw_bytes(rendered.encode())
                    resources = {value.final_url: value for value in cache.values()}
                    return replace(
                        main,
                        url=raw.url,
                        content=content.strip(),
                        metadata={
                            **main.metadata,
                            "source_url": raw.url,
                            "extractor": "playwright",
                            "rendered_sha256": derived_hash,
                            "rendered_storage_key": derived_key,
                            "resources": [
                                {
                                    key: value.metadata[key]
                                    for key in (
                                        "source_url",
                                        "final_url",
                                        "raw_sha256",
                                        "raw_storage_key",
                                        "fetched_at",
                                    )
                                }
                                for value in resources.values()
                            ],
                        },
                    )
                finally:
                    await browser.close()
        except Exception as exc:
            return replace(raw, content="", error=f"playwright: {type(exc).__name__}")

    # Compatibility entry points use the same guarded retrieval and offline engines.
    async def _fetch_trafilatura(self, url: str) -> FetchResult:
        raw = await self.fetch_raw(url)
        return raw if raw.error else await self._extract_trafilatura(raw)

    async def _fetch_crawl4ai(self, url: str) -> FetchResult:
        raw = await self.fetch_raw(url)
        return raw if raw.error else await self._extract_crawl4ai(raw)

    async def _fetch_playwright(self, url: str) -> FetchResult:
        raw = await self.fetch_raw(url)
        return raw if raw.error else await self._extract_playwright(raw)

    async def _store_raw(self, url: str, content: str) -> str:
        return store_raw_bytes(content.encode())[0]


async def fetch_document(url: str, config: FetchConfig | None = None) -> FetchResult:
    async with DocumentFetcher(config) as fetcher:
        return await fetcher.fetch(url)
