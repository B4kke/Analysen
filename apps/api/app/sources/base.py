from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    external_id: str
    payload: dict[str, Any]
    source_url: str


@dataclass(frozen=True)
class DiscoveryResult:
    provider: str
    url: str
    title: str | None = None
    snippet: str | None = None
    rank: int | None = None


class SourceAdapter(ABC):
    source_id: str

    @abstractmethod
    async def fetch(self, identifier: str) -> SourceRecord:
        raise NotImplementedError


class DiscoveryAdapter(ABC):
    provider_id: str

    @abstractmethod
    async def search(self, query: str, **kwargs: Any) -> list[DiscoveryResult]:
        raise NotImplementedError
