"""Shared corpus loader — single source of truth for document loading.

Both knowledge_server and hybrid_knowledge_server share the same CorpusLoader
instance to avoid duplicate file I/O and memory.
"""

from pathlib import Path


class CorpusLoader:
    """Loads .txt/.md files recursively from a corpus directory.

    Usage:
        loader = CorpusLoader("rag/corpus")
        docs = loader.docs          # list[tuple[id, text]]
        loader.reload()             # re-scan directory for new files
    """

    def __init__(self, corpus_dir: str):
        self._dir = Path(corpus_dir)
        self._docs: list[tuple[str, str]] = []
        self._load()

    @property
    def dir(self) -> Path:
        return self._dir

    @property
    def docs(self) -> list[tuple[str, str]]:
        return self._docs

    def __len__(self) -> int:
        return len(self._docs)

    def _load(self) -> None:
        if not self._dir.exists():
            return
        docs: list[tuple[str, str]] = []
        for p in sorted(self._dir.rglob("*.txt")):
            if p.is_file():
                docs.append((str(p.relative_to(self._dir)), p.read_text(encoding="utf-8")))
        for p in sorted(self._dir.rglob("*.md")):
            if p.is_file():
                docs.append((str(p.relative_to(self._dir)), p.read_text(encoding="utf-8")))
        self._docs = docs

    def reload(self) -> int:
        """Re-scan corpus directory. Returns number of docs loaded."""
        self._load()
        return len(self._docs)

    def get(self, doc_id: str) -> str | None:
        """Get document text by id."""
        for i, (did, text) in enumerate(self._docs):
            if did == doc_id:
                return text
        return None
