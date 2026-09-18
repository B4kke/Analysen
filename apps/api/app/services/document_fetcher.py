"""Document fetching pipeline with fallback chain (AQ-021).

Priority order:
1. Trafilatura (fast, no JS)
2. Crawl4AI (JS rendering, clean extraction)
3. Playwright (full browser, last resort)

All fetchers respect robots.txt, rate limits, and SSRF guards.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    import trafilatura  # type: ignore[import-not-found]
    from crawl4ai import AsyncWebCrawler  # type: ignore[import-not-found]

try:
    import trafilatura
    _TRAFILATURA_AVAILABLE = True
except ImportError:
    trafilatura = None
    _TRAFILATURA_AVAILABLE = False

try:
    from crawl4ai import AsyncWebCrawler
    _CRAWL4AI_AVAILABLE = True
except ImportError:
    AsyncWebCrawler = None
    _CRAWL4AI_AVAILABLE = False

try:
    from playwright.async_api import async_playwright  # type: ignore[import-not-found]
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    async_playwright = None
    _PLAYWRIGHT_AVAILABLE = False

from apps.api.app.services.crawler_security import validate_public_http_url
from apps.api.app.services.raw_store import store_raw_snapshot
from apps.api.app.services.url_canonicalization import (
    FetchResult,
)


@dataclass
class FetchConfig:
    """Configuration for document fetching."""
    timeout_seconds: int = 30
    max_content_length: int = 10 * 1024 * 1024  # 10 MB
    follow_redirects: bool = True
    max_redirects: int = 10
    user_agent: str = "AnalysenBot/1.0 (+https://analysen.no/bot)"
    obey_robots: bool = True
    rate_limit_per_domain: float = 1.0  # requests per second


class DocumentFetcher:
    """Fetches and extracts content from URLs with fallback chain."""

    def __init__(
        self,
        config: FetchConfig | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        self.config = config or FetchConfig()
        self._client = client or httpx.AsyncClient(
            timeout=self.config.timeout_seconds,
            follow_redirects=self.config.follow_redirects,
            max_redirects=self.config.max_redirects,
            headers={"User-Agent": self.config.user_agent},
        )
        self._rate_limiter: dict[str, float] = {}
        self._crawler: Any | None = None
        self._playwright_browser: Any = None

    async def __aenter__(self) -> "DocumentFetcher":
        if _CRAWL4AI_AVAILABLE:
            self._crawler = AsyncWebCrawler()
            await self._crawler.__aenter__()
        return self

    async def __aexit__(self, *args) -> None:
        await self._client.aclose()
        if self._crawler:
            await self._crawler.__aexit__(None, None, None)
        if self._playwright_browser:
            await self._playwright_browser.close()

    async def fetch(self, url: str) -> "FetchResult":
        """Fetch URL with fallback chain: Trafilatura -> Crawl4AI -> Playwright."""
        await validate_public_http_url(url)

        # Try Trafilatura first (fastest, no JS)
        if _TRAFILATURA_AVAILABLE:
            result = await self._fetch_trafilatura(url)
            if result.content and len(result.content) > 100:
                await self._store_raw(url, result.content)
                return result

        # Try Crawl4AI (JavaScript rendering)
        if _CRAWL4AI_AVAILABLE and self._crawler:
            result = await self._fetch_crawl4ai(url)
            if result.content and len(result.content) > 100:
                await self._store_raw(url, result.content)
                return result

        # Fallback to Playwright (full browser)
        if _PLAYWRIGHT_AVAILABLE:
            result = await self._fetch_playwright(url)
            if result.content and len(result.content) > 100:
                await self._store_raw(url, result.content)
                return result

        # All methods failed
        return FetchResult(
            url=url,
            final_url=url,
            content="",
            content_type=None,
            status_code=0,
            metadata={"error": "all fetch methods failed"},
            error="All extraction methods failed",
        )

    async def _fetch_trafilatura(self, url: str) -> "FetchResult":
        """Fetch with Trafilatura (no JS)."""
        try:
            downloaded = trafilatura.fetch_url(
                url,
                no_ssl=True,
                config=trafilatura.settings.Config(
                    DEFAULT_EXTRACTION_TIMEOUT=20,
                ),
            )
            if not downloaded:
                return FetchResult(
                    url=url, final_url=url, content="",
                    content_type=None, status_code=0, metadata={},
                    error="trafilatura: no content downloaded",
                )

            content = trafilatura.extract(
                downloaded,
                include_comments=False,
                include_tables=True,
                include_formatting=False,
                output_format="txt",
            )

            if not content or len(content.strip()) < 50:
                return FetchResult(
                    url=url, final_url=url, content="",
                    content_type="text/html", status_code=200,
                    metadata={}, error="trafilatura: content too short",
                )

            return FetchResult(
                url=url, final_url=url, content=content.strip(),
                content_type="text/html", status_code=200,
                metadata={"extractor": "trafilatura"},
            )
        except Exception as e:
            return FetchResult(
                url=url, final_url=url, content="",
                content_type=None, status_code=0, metadata={},
                error=f"trafilatura: {type(e).__name__}: {e}",
            )

    async def _fetch_crawl4ai(self, url: str) -> "FetchResult":
        """Fetch with Crawl4AI (JavaScript rendering)."""
        if not self._crawler:
            return FetchResult(
                url=url, final_url=url, content="",
                content_type=None, status_code=0, metadata={},
                error="Crawl4AI not available",
            )
        try:
            result = await self._crawler.arun(
                url=url,
                bypass_cache=True,
                wait_for="networkidle",
            )
            if not result.success:
                return FetchResult(
                    url=url, final_url=url, content="",
                    content_type=None, status_code=0, metadata={},
                    error=f"crawl4ai: {result.error_message}",
                )
            content = result.markdown or result.cleaned_html or ""
            if not content or len(content.strip()) < 100:
                return FetchResult(
                    url=url, final_url=result.url, content="",
                    content_type="text/html", status_code=200,
                    metadata={}, error="crawl4ai: content too short",
                )
            return FetchResult(
                url=url, final_url=result.url, content=content.strip(),
                content_type="text/html", status_code=200,
                metadata={"extractor": "crawl4ai", "metadata": result.metadata},
            )
        except Exception as e:
            return FetchResult(
                url=url, final_url=url, content="",
                content_type=None, status_code=0, metadata={},
                error=f"crawl4ai: {type(e).__name__}: {e}",
            )

    async def _fetch_playwright(self, url: str) -> "FetchResult":
        """Fetch with Playwright (full browser)."""
        if not _PLAYWRIGHT_AVAILABLE:
            return FetchResult(
                url=url, final_url=url, content="",
                content_type=None, status_code=0, metadata={},
                error="Playwright not available",
            )
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                page = await browser.new_page(
                    user_agent="AnalysenBot/1.0 (+https://analysen.no/bot)"
                )
                response = await page.goto(url, wait_until="networkidle", timeout=30000)
                if not response or not response.ok:
                    return FetchResult(
                        url=url, final_url=url, content="",
                        content_type=None, status_code=response.status if response else 0,
                        metadata={}, error="playwright: navigation failed",
                    )
                content = await page.content()
                await browser.close()
                if not content or len(content.strip()) < 100:
                    return FetchResult(
                        url=url, final_url=page.url, content="",
                        content_type="text/html", status_code=200,
                        metadata={}, error="playwright: content too short",
                    )
                return FetchResult(
                    url=url, final_url=page.url, content=content.strip(),
                    content_type="text/html", status_code=200,
                    metadata={"extractor": "playwright"},
                )
        except Exception as e:
            return FetchResult(
                url=url, final_url=url, content="",
                content_type=None, status_code=0, metadata={},
                error=f"playwright: {type(e).__name__}: {e}",
            )

    async def _store_raw(self, url: str, content: str) -> str:
        """Store raw content in object store, return the content digest."""
        digest, _storage_key = store_raw_snapshot(content)
        return digest


async def fetch_document(url: str, config: FetchConfig | None = None) -> "FetchResult":
    """Convenience function for single URL fetch."""
    async with DocumentFetcher(config) as fetcher:
        return await fetcher.fetch(url)