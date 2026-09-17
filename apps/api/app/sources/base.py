from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    external_id: str
    payload: dict[str, Any]
    source_url: str


class SourceAdapter(ABC):
    source_id: str

    @abstractmethod
    async def fetch(self, identifier: str) -> SourceRecord:
        raise NotImplementedError
