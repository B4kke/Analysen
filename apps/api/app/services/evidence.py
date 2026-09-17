import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class Snapshot:
    sha256: str
    path: Path
    fetched_at: datetime


def store_snapshot(data: bytes, directory: Path, suffix: str = ".bin") -> Snapshot:
    digest = hashlib.sha256(data).hexdigest()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{digest}{suffix}"
    if not path.exists():
        path.write_bytes(data)
    return Snapshot(sha256=digest, path=path, fetched_at=datetime.now(UTC))
