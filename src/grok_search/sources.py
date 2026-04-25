import asyncio
import uuid
from collections import OrderedDict


def new_session_id() -> str:
    return uuid.uuid4().hex[:12]


class SourcesCache:
    def __init__(self, max_size: int = 256):
        self._max_size = max_size
        self._lock = asyncio.Lock()
        self._cache: OrderedDict[str, list[dict]] = OrderedDict()

    async def set(self, session_id: str, sources: list[dict]) -> None:
        async with self._lock:
            self._cache[session_id] = sources
            self._cache.move_to_end(session_id)
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    async def get(self, session_id: str) -> list[dict] | None:
        async with self._lock:
            sources = self._cache.get(session_id)
            if sources is None:
                return None
            self._cache.move_to_end(session_id)
            return sources


def merge_sources(*source_lists: list[dict]) -> list[dict]:
    seen: set[str] = set()
    merged: list[dict] = []
    for sources in source_lists:
        for item in sources or []:
            url = (item or {}).get("url")
            if not isinstance(url, str) or not url.strip():
                continue
            url = url.strip()
            if url in seen:
                continue
            seen.add(url)
            merged.append(item)
    return merged
