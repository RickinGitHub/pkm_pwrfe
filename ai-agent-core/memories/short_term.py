import json
from collections import deque
from pathlib import Path
from time import time


class ShortTerm:
    def __init__(self, path: str, max_entries: int = 50):
        self._path = Path(path)
        self._max = max_entries
        self._buf: deque[dict] = deque(maxlen=max_entries)
        self._load()

    def append(self, role: str, content: str) -> None:
        self._buf.append({"role": role, "content": content, "ts": time()})
        self._save()

    def recent(self, n: int = 10) -> list[dict]:
        if n <= 0:
            return []
        items = list(self._buf)[-n:]
        return [dict(item) for item in items]

    def clear(self) -> None:
        self._buf.clear()
        self._save()

    def _load(self) -> None:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        for entry in data:
            self._buf.append(entry)

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("w", encoding="utf-8") as f:
            json.dump(list(self._buf), f, ensure_ascii=False, indent=2)
