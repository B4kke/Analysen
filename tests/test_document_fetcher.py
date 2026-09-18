"""Unit tests for the document fetcher contract (AQ-021 follow-up).

No network access: engine availability is patched off, unsafe URLs are
rejected before any fetch, and raw storage uses an isolated directory.
"""

import hashlib

import pytest

from apps.api.app.services import document_fetcher
from apps.api.app.services.crawler_security import UnsafeUrl
from apps.api.app.services.document_fetcher import DocumentFetcher


@pytest.fixture
def isolated_raw_store(monkeypatch, tmp_path):
    from apps.api.app.core import config

    monkeypatch.setenv("RAW_EVIDENCE_DIR", str(tmp_path / "raw"))
    config.get_settings.cache_clear()
    yield tmp_path / "raw"
    config.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_store_raw_persists_content_not_url(isolated_raw_store) -> None:
    fetcher = DocumentFetcher()
    url = "https://example.com/article?utm_source=x"
    content = "<html><body>Real fetched bytes</body></html>"
    digest = await fetcher._store_raw(url, content)

    assert digest == hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert digest != hashlib.sha256(url.encode("utf-8")).hexdigest()
    stored = next((isolated_raw_store).rglob(digest))
    assert stored.read_text(encoding="utf-8") == content


@pytest.mark.asyncio
async def test_fetch_rejects_unsafe_url_before_engines(monkeypatch) -> None:
    fetcher = DocumentFetcher()
    with pytest.raises(UnsafeUrl):
        await fetcher.fetch("http://localhost:9/internal")


@pytest.mark.asyncio
async def test_fetch_fails_closed_without_engines(monkeypatch) -> None:
    async def allow_any(url: str) -> None:
        return None

    monkeypatch.setattr(document_fetcher, "validate_public_http_url", allow_any)
    monkeypatch.setattr(document_fetcher, "_TRAFILATURA_AVAILABLE", False)
    monkeypatch.setattr(document_fetcher, "_CRAWL4AI_AVAILABLE", False)
    monkeypatch.setattr(document_fetcher, "_PLAYWRIGHT_AVAILABLE", False)
    fetcher = DocumentFetcher()
    result = await fetcher.fetch("https://example.com/article")
    assert result.content == ""
    assert result.error == "All extraction methods failed"
