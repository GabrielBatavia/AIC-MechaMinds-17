# app/domain/ports.py
from abc import ABC, abstractmethod
from pathlib import Path

class OcrPort(ABC):
    @abstractmethod
    async def extract(self, img: Path) -> str: ...

class SatusehatPort(ABC):
    @abstractmethod
    async def smart_lookup(self, nie: str | None, text: str | None): ...

class RepoPort(ABC):
    @abstractmethod
    async def save_lookup(self, nie: str, status: str): ...

class CachePort(ABC):
    async def get(self, key: str): ...
    async def set(self, key: str, value, ttl: int = 43200): ...

class LlmPort(ABC):
    @abstractmethod
    async def explain(self, verdict): ...
