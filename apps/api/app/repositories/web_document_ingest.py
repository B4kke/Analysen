"""Provenance-preserving persistence for guarded web fetches.

This adapter deliberately persists a document and locator evidence only. It
does not create claims or authorize additional research.
"""

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.domain.models import SourceRegistryRecord
from apps.api.app.repositories import claims_evidence
from apps.api.app.services.crawler_security import validate_public_http_url
from apps.api.app.services.url_canonicalization import FetchResult, canonicalize_url

_STORAGE_KEY = re.compile(r"^sha256/[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{64}$")


def _raw_path(storage_key: str) -> Path:
    from apps.api.app.core.config import get_settings

    return Path(get_settings().raw_evidence_dir) / storage_key


def _validate_source(source: SourceRegistryRecord, *urls: str) -> None:
    from apps.api.app.core.config import get_settings

    _models, sources, _policies = get_settings().validate_yaml_configs()
    configured = sources.sources.get(source.id)
    if configured is None or not configured.enabled or configured.discovery_only:
        raise ValueError("source is disabled, unknown, or discovery-only")
    if configured.access != source.access_class:
        raise ValueError("source access class does not match configuration")
    if configured.evidence_tier != source.evidence_tier:
        raise ValueError("source evidence tier does not match configuration")
    if configured.license != source.license:
        raise ValueError("source license does not match configuration")
    configured_url = (
        configured.base_url or configured.url or configured.index_url or configured.endpoint
    )
    if configured_url and str(configured_url).rstrip("/") != (source.base_url or "").rstrip("/"):
        raise ValueError("source base URL does not match configuration")
    if not configured_url and source.base_url:
        raise ValueError("source base URL is not configured")
    if source.base_url:
        base_host = urlsplit(source.base_url).hostname
        if base_host and any(urlsplit(url).hostname != base_host for url in urls):
            raise ValueError("fetch URL host does not match source base URL")


async def persist_web_document(
    session: AsyncSession,
    investigation_id: UUID,
    source: SourceRegistryRecord,
    result: FetchResult,
) -> tuple[UUID, UUID]:
    """Persist ``Source -> Document -> investigation link -> Evidence``.

    The fetch result must carry the exact original bytes and immutable raw
    metadata. Validation completes before any database write, so malformed or
    failed fetches cannot leave partial provenance rows.
    """
    if result.error:
        raise ValueError(f"cannot ingest failed fetch: {result.error}")
    raw_bytes: bytes | None = getattr(result, "raw_bytes", None)
    metadata: dict[str, Any] = result.metadata or {}
    storage_key = metadata.get("raw_storage_key")
    digest = metadata.get("raw_sha256")
    fetched_at = getattr(result, "fetched_at", None)
    if not raw_bytes or not storage_key or not digest or not fetched_at:
        raise ValueError("fetch result lacks raw bytes, hash, storage key, or fetched_at")
    if not result.url or not result.final_url:
        raise ValueError("fetch result lacks source/final URL")
    if metadata.get("source_url") != result.url or metadata.get("final_url") != result.final_url:
        raise ValueError("fetch metadata URL provenance does not match result")
    metadata_time = metadata.get("fetched_at")
    if not isinstance(metadata_time, str):
        raise ValueError("fetch metadata lacks ISO fetched_at")
    try:
        parsed_metadata_time = datetime.fromisoformat(metadata_time)
    except ValueError as exc:
        raise ValueError("fetch metadata fetched_at is not ISO-8601") from exc
    if not isinstance(fetched_at, datetime) or parsed_metadata_time != fetched_at:
        raise ValueError("fetched_at does not match fetch metadata")
    if not isinstance(storage_key, str) or not isinstance(digest, str):
        raise ValueError("raw storage key and digest must be strings")
    expected_key = f"sha256/{digest[:2]}/{digest[2:4]}/{digest}"
    if not _STORAGE_KEY.fullmatch(storage_key) or storage_key != expected_key:
        raise ValueError("invalid content-addressed storage key")
    await validate_public_http_url(result.url)
    await validate_public_http_url(result.final_url)
    _validate_source(source, result.url, result.final_url)
    actual_digest = hashlib.sha256(raw_bytes).hexdigest()
    if actual_digest != digest:
        raise ValueError("raw bytes do not match fetch result SHA-256")
    raw_root = _raw_path(".")
    stored_path = _raw_path(storage_key).resolve()
    if raw_root.resolve() not in stored_path.parents:
        raise ValueError("raw storage key escapes configured raw store")
    if not stored_path.is_file() or stored_path.read_bytes() != raw_bytes:
        raise ValueError("immutable raw snapshot is absent or differs from fetched bytes")
    if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
        raise ValueError("fetched_at must be timezone-aware")

    await claims_evidence.upsert_source(session, source)
    document_id = await claims_evidence.upsert_document(
        session,
        source_id=source.id,
        original_url=result.url,
        canonical_url=canonicalize_url(result.final_url),
        mime_type=result.content_type or "application/octet-stream",
        sha256=digest,
        raw_storage_key=storage_key,
        extracted_text=result.content or None,
        parser_metadata={
            "fetch_final_url": result.final_url,
            "fetch_metadata": metadata,
        },
        fetched_at=fetched_at,
    )
    await claims_evidence.attach_document(session, investigation_id, document_id)
    evidence_id = await claims_evidence.store_evidence(
        session,
        document_id,
        "document_excerpt",
        {"source_url": result.url, "final_url": result.final_url},
        result.content[:2000] if result.content else None,
        None,
    )
    return document_id, evidence_id
