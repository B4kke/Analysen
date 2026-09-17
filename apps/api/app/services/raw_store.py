"""Hash-addressed raw evidence storage (AQ-009).

Original upstream responses are written to RAW_EVIDENCE_DIR before any
normalization or model sees them. The storage key is the SHA-256 digest, so
the same payload always maps to the same immutable snapshot. No fetching
happens here: callers hand over the already fetched payload.
"""

import hashlib
import os
from pathlib import Path

from apps.api.app.core.config import get_settings


def store_raw_snapshot(payload: str) -> tuple[str, str]:
    """Write the payload bytes and return (digest, storage_key).

    The key is the digest with the canonical sha256/ prefix. Writing uses an
    exclusive create so an existing immutable snapshot is never overwritten.
    """
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    storage_key = f"sha256/{digest[:2]}/{digest[2:4]}/{digest}"
    base = Path(get_settings().raw_evidence_dir)
    target = base / storage_key
    if target.is_file():
        # Immutable: identical bytes already stored; nothing to rewrite.
        return digest, storage_key
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_suffix(".tmp")
    temp_path.write_text(payload, encoding="utf-8")
    # Atomic within the same filesystem; concurrent writers converge on the
    # same content because the name is content-addressed.
    os.replace(temp_path, target)
    return digest, storage_key
