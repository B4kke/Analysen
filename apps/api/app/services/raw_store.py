"""Hash-addressed raw evidence storage (AQ-009).

Original upstream responses are written to RAW_EVIDENCE_DIR before any
normalization or model sees them. The storage key is the SHA-256 digest, so
the same payload always maps to the same immutable snapshot. No fetching
happens here: callers hand over the already fetched payload.
"""

import hashlib
import os
import tempfile
from contextlib import suppress
from pathlib import Path

from apps.api.app.core.config import get_settings


def store_raw_bytes(payload: bytes) -> tuple[str, str]:
    """Write exactly the fetched bytes and return ``(digest, storage_key)``."""
    digest = hashlib.sha256(payload).hexdigest()
    storage_key = f"sha256/{digest[:2]}/{digest[2:4]}/{digest}"
    base = Path(get_settings().raw_evidence_dir)
    target = base / storage_key
    if target.is_file():
        with target.open("rb") as handle:
            if hashlib.file_digest(handle, "sha256").hexdigest() != digest:
                raise ValueError("stored raw snapshot failed integrity validation")
        return digest, storage_key
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{digest}.", dir=target.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        with suppress(FileExistsError):
            os.link(temp_path, target)
        with target.open("rb") as handle:
            if hashlib.file_digest(handle, "sha256").hexdigest() != digest:
                raise ValueError("stored raw snapshot failed integrity validation")
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return digest, storage_key


def store_raw_snapshot(payload: str) -> tuple[str, str]:
    """Write the payload bytes and return (digest, storage_key).

    The key is the digest with the canonical sha256/ prefix. Writing uses an
    exclusive create so an existing immutable snapshot is never overwritten.
    """
    return store_raw_bytes(payload.encode("utf-8"))


class RawSnapshotUnavailable(ValueError):
    """The recorded original cannot be safely loaded or fails its content hash."""


def load_raw_bytes(storage_key: str, digest: str) -> bytes:
    """Return hash-verified stored bytes without accepting arbitrary paths."""
    expected_key = f"sha256/{digest[:2]}/{digest[2:4]}/{digest}"
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise RawSnapshotUnavailable("invalid raw snapshot hash")
    if storage_key != expected_key:
        raise RawSnapshotUnavailable("invalid raw snapshot storage key")
    root = Path(get_settings().raw_evidence_dir).resolve()
    target = (root / storage_key).resolve()
    if root not in target.parents:
        raise RawSnapshotUnavailable("raw snapshot path is outside raw store")
    try:
        content = target.read_bytes()
    except OSError as exc:
        raise RawSnapshotUnavailable("raw snapshot is unavailable") from exc
    if hashlib.sha256(content).hexdigest() != digest:
        raise RawSnapshotUnavailable("raw snapshot failed integrity validation")
    return content
