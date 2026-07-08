"""Document metadata index — fast tag/date/source filtering.

Parses document filenames and content for structured metadata.
Provides O(1) tag lookup — much faster than full-text search for
filtering "show me all [精华][职场] docs".
"""

import re
from datetime import datetime
from pathlib import Path


# Extract tags like [精华], [科技], [职场], [精华++]
_TAG_RE = re.compile(r"\[([^\]]+)\]")

# Extract date from filenames like 20260707_025831_...
_DATE_RE = re.compile(r"(\d{8})_\d{6}")

# Extract title from first # heading
_TITLE_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)

# Extract source URL
_URL_RE = re.compile(r"\*\*URL\*\*:\s*<([^>]+)>|> \*\*URL\*\*: <([^>]+)>")


class DocMeta:
    """Structured metadata for a single document."""

    __slots__ = ("doc_id", "title", "tags", "date", "source_url", "chars", "path")

    def __init__(
        self,
        doc_id: str = "",
        title: str = "",
        tags: list[str] | None = None,
        date: str = "",
        source_url: str = "",
        chars: int = 0,
        path: str = "",
    ):
        self.doc_id = doc_id
        self.title = title
        self.tags = tags or []
        self.date = date
        self.source_url = source_url
        self.chars = chars
        self.path = path

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "tags": self.tags,
            "date": self.date,
            "source_url": self.source_url,
            "chars": self.chars,
        }


class MetadataIndex:
    """Fast in-memory index of document metadata.

    Usage:
        idx = MetadataIndex("rag/corpus")
        idx.build()
        docs = idx.filter(tags=["精华", "职场"])  # O(1) per tag
    """

    def __init__(self, corpus_dir: str):
        self._dir = Path(corpus_dir)
        self._docs: list[DocMeta] = []
        self._by_tag: dict[str, list[DocMeta]] = {}
        self._by_id: dict[str, DocMeta] = {}

    # ---- build ----

    def build(self) -> int:
        """Scan corpus and build metadata index. Returns doc count."""
        self._docs.clear()
        self._by_tag.clear()
        self._by_id.clear()

        if not self._dir.exists():
            return 0

        for p in sorted(self._dir.rglob("*.md")):
            if not p.is_file():
                continue
            doc_id = str(p.relative_to(self._dir))
            text = p.read_text(encoding="utf-8")
            meta = self._extract(doc_id, p, text)
            self._docs.append(meta)
            self._by_id[doc_id] = meta
            for tag in meta.tags:
                tag_lower = tag.lower()
                if tag_lower not in self._by_tag:
                    self._by_tag[tag_lower] = []
                self._by_tag[tag_lower].append(meta)

        return len(self._docs)

    def _extract(self, doc_id: str, path: Path, text: str) -> DocMeta:
        # Tags from filename
        tags = _TAG_RE.findall(path.name)

        # Title from first # heading
        title = ""
        m = _TITLE_RE.search(text)
        if m:
            title = m.group(1).strip()

        # Date from filename or fetch timestamp
        date = ""
        m = _DATE_RE.search(path.name)
        if m:
            date = m.group(1)

        # Source URL
        source_url = ""
        m = _URL_RE.search(text[:2000])
        if m:
            source_url = m.group(1) or m.group(2) or ""

        return DocMeta(
            doc_id=doc_id,
            title=title,
            tags=tags,
            date=date,
            source_url=source_url,
            chars=len(text),
            path=str(path),
        )

    # ---- query ----

    @property
    def docs(self) -> list[DocMeta]:
        return self._docs

    @property
    def all_tags(self) -> list[str]:
        return sorted(self._by_tag.keys())

    def filter(
        self,
        tags: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        source_contains: str | None = None,
        max_results: int = 50,
    ) -> list[DocMeta]:
        """Filter docs by metadata. All conditions are AND-ed."""
        if tags:
            tag_lower = {t.lower() for t in tags}
            candidates: set[str] | None = None
            for t in tag_lower:
                ids = {m.id for m in self._by_tag.get(t, [])}
                if candidates is None:
                    candidates = ids
                else:
                    candidates &= ids
            if candidates is None:
                candidates = set()
            result = [self._by_id[did] for did in candidates if did in self._by_id]
        else:
            result = list(self._docs)

        if date_from:
            result = [d for d in result if d.date >= date_from]
        if date_to:
            result = [d for d in result if d.date <= date_to]
        if source_contains:
            result = [d for d in result if source_contains.lower() in d.source_url.lower()]

        return result[:max_results]

    def get(self, doc_id: str) -> DocMeta | None:
        return self._by_id.get(doc_id)
