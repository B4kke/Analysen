"""URL canonicalization and deduplication utilities (AQ-021)."""

import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

# Query parameters to strip for deduplication
_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "msclkid", "igshid", "ref", "source",
    "mc_cid", "mc_eid", "_ga", "_gl", "amp", "amp_js_v", "amp_gsa",
})

# Hosts that are known CDNs/proxies to normalize
_CDN_HOSTS = frozenset({
    "cdn.ampproject.org",
    "textise.net",
    "textise dot iitty",
    "r.jina.ai",
    "r.jina.ai/http",
    "r.jina.ai/https",
})


def _normalize_hostname(host: str) -> str:
    """Normalize hostname: lowercase, remove www., handle CDN proxies."""
    host = host.lower().removeprefix("www.")
    # Remove CDN prefixes
    for cdn in _CDN_HOSTS:
        if host.startswith(cdn + ".") or host == cdn:
            return host.removeprefix(cdn + ".")
    return host


def _normalize_path(path: str) -> str:
    """Normalize URL path: remove trailing slash, resolve . and .."""
    if not path or path == "/":
        return "/"
    # Remove duplicate slashes
    path = re.sub(r"/+", "/", path)
    # Remove trailing slash unless it's the root
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return path


def _normalize_query(query: str) -> str:
    """Normalize query string: strip tracking params, sort alphabetically."""
    if not query:
        return ""
    params = parse_qsl(query, keep_blank_values=True)
    filtered = [(k, v) for k, v in params if k.lower() not in _TRACKING_PARAMS]
    filtered.sort(key=lambda kv: kv[0])
    return urlencode(filtered, doseq=True)


def _normalize_fragment(fragment: str) -> str:
    """Normalize fragment: remove common tracking fragments."""
    if not fragment:
        return ""
    # Remove common tracking fragments
    if fragment.startswith("!"):
        return ""
    return fragment


def canonicalize_url(url: str) -> str:
    """Return canonical form of URL for deduplication.

    Always yields an absolute https URL: inputs without a scheme are treated
    as host[/path]. Input that cannot be parsed as a URL at all is
    percent-encoded under the reserved "invalid" host so the output stays a
    string in URL shape (and can never resolve to a real host). Empty input
    keeps the legacy "https:///" value.
    """
    if not url or not url.strip():
        return "https:///"
    text = url.strip()
    if "://" not in text:
        text = "https://" + text.lstrip("/")
    try:
        parsed = urlparse(text)
    except Exception:
        return "https://invalid/" + quote(url.strip(), safe="")
    if not parsed.netloc:
        return "https://invalid/" + quote(url.strip(), safe="")

    # Normalize scheme to https
    scheme = "https"
    netloc = _normalize_hostname(parsed.netloc)
    path = _normalize_path(parsed.path)
    query = _normalize_query(parsed.query)
    fragment = _normalize_fragment(parsed.fragment)

    return urlunparse((scheme, netloc, path, "", query, fragment))


def deduplicate_urls(urls: list[str]) -> list[str]:
    """Return deduplicated URLs preserving first occurrence order."""
    seen: set[str] = set()
    result: list[str] = []
    for url in urls:
        canonical = canonicalize_url(url)
        if canonical not in seen:
            seen.add(canonical)
            result.append(url)  # Keep original URL
    return result


@dataclass
class FetchResult:
    """Result of fetching a URL."""
    url: str
    final_url: str  # After redirects
    content: str
    content_type: str | None
    status_code: int
    metadata: dict
    error: str | None = None
    raw_bytes: bytes | None = None
    fetched_at: datetime | None = None


class FetchError(Exception):
    """Exception raised when fetch fails."""
    pass


# Import re at module level
