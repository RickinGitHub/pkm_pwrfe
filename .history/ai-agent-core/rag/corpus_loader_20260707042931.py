"""Shared corpus loader — single source of truth for document loading.

Both knowledge_server and hybrid_knowledge_server share the same CorpusLoader
instance to avoid duplicate file I/O and memory.

Supports optional chunking for fine-grained retrieval on large documents.
"""

from pathlib import Path

from rag.chunker import TextChunker


class CorpusLoader:
    """Loads .txt/.md files recursively from a corpus directory.

    Usage:
        loader = CorpusLoader("rag/corpus")
        docs = loader.docs          # list[tuple[id, text]]

        # With chunking enabled:
        loader = CorpusLoader("rag/corpus", chunk=True, chunk_size=1200)
        # Each large doc split into chunks like "doc.md#0", "doc.md#1", ...

        loader.reload()             # re-scan directory for new files
    """

    def __init__(
        self,
        corpus_dir: str,
        chunk: bool = False,
        chunk_size: int = 1200,
        chunk_overlap: int = 150,
        chunk_strategy: str = "paragraph",
    ):
        self._dir = Path(corpus_dir)
        self._chunk_enabled = chunk
        self._chunker = TextChunker(
            strategy=chunk_strategy,
            max_chars=chunk_size,
            overlap_chars=chunk_overlap,
        ) if chunk else None
        self._docs: list[tuple[str, str]] = []
        self._load()

    @property
    def dir(self) -> Path:
        return self._dir

    @property
    def docs(self) -> list[tuple[str, str]]:
        return self._docs

    @property
    def chunk_enabled(self) -> bool:
        return self._chunk_enabled

    def __len__(self) -> int:
        return len(self._docs)

    def _load(self) -> None:
        if not self._dir.exists():
            return
        docs: list[tuple[str, str]] = []
        for p in sorted(self._dir.rglob("*.txt")):
            if p.is_file():
                doc_id = str(p.relative_to(self._dir))
                text = p.read_text(encoding="utf-8")
                docs.extend(self._maybe_chunk(doc_id, text))
        for p in sorted(self._dir.rglob("*.md")):
            if p.is_file():
                doc_id = str(p.relative_to(self._dir))
                text = p.read_text(encoding="utf-8")
                docs.extend(self._maybe_chunk(doc_id, text))
        self._docs = docs

    def _maybe_chunk(self, doc_id: str, text: str) -> list[tuple[str, str]]:
        """If chunking enabled, split text; otherwise return as single doc."""
        if self._chunker is None:
            return [(doc_id, text)]
        chunks = self._chunker.chunk(doc_id, text)
        return chunks if chunks else [(doc_id, text)]

    def reload(self) -> int:
        """Re-scan corpus directory. Returns number of docs loaded."""
        self._load()
        return len(self._docs)

    def get(self, doc_id: str) -> str | None:
        """Get document text by id."""
        for did, text in self._docs:
            if did == doc_id:
                return text
        return None
