"""Document chunker — splits large texts into smaller chunks for fine-grained retrieval.

Strategies:
  - "paragraph": split on double-newline, merge short paragraphs, cap at max_chars
  - "fixed":    sliding window of max_chars with overlap_chars

Each chunk preserves its source doc_id via suffix like "#chunk_0".
"""

import re


class TextChunker:
    """Split documents into overlapping or paragraph-based chunks."""

    def __init__(
        self,
        strategy: str = "paragraph",
        max_chars: int = 1200,
        overlap_chars: int = 150,
    ):
        if strategy not in ("paragraph", "fixed"):
            raise ValueError(f"unknown strategy: {strategy}")
        self._strategy = strategy
        self._max = max_chars
        self._overlap = overlap_chars

    def chunk(self, doc_id: str, text: str) -> list[tuple[str, str]]:
        """Return list of (chunk_id, chunk_text) for a document."""
        if self._strategy == "paragraph":
            return self._chunk_paragraphs(doc_id, text)
        return self._chunk_fixed(doc_id, text)

    # ---- paragraph strategy ----

    def _chunk_paragraphs(self, doc_id: str, text: str) -> list[tuple[str, str]]:
        raw = [p.strip() for p in re.split(r"\n\s*\n", text)]
        paragraphs = [p for p in raw if p]
        if not paragraphs:
            return [(f"{doc_id}#0", text.strip())]

        chunks: list[tuple[str, str]] = []
        buf: list[str] = []
        buf_len = 0

        def flush() -> None:
            nonlocal buf, buf_len
            if buf:
                chunks.append((f"{doc_id}#{len(chunks)}", "\n\n".join(buf)))
                buf = []
                buf_len = 0

        for para in paragraphs:
            if buf_len + len(para) > self._max and buf:
                flush()
            # If a single paragraph exceeds max_chars, split it further
            if len(para) > self._max:
                if buf:
                    flush()
                for sub in self._split_long_paragraph(para):
                    chunks.append((f"{doc_id}#{len(chunks)}", sub))
            else:
                buf.append(para)
                buf_len += len(para)

        flush()

        # Merge last chunk if too small (< 200 chars) and there's a previous one
        if len(chunks) >= 2 and len(chunks[-1][1]) < 200:
            last_id, last_text = chunks.pop()
            prev_id, prev_text = chunks.pop()
            merged = prev_text + "\n\n" + last_text
            if len(merged) <= self._max * 1.2:
                chunks.append((prev_id, merged))
            else:
                chunks.append((prev_id, prev_text))
                chunks.append((last_id, last_text))

        return chunks

    def _split_long_paragraph(self, text: str) -> list[str]:
        """Split a single overlong paragraph into sentence-boundary chunks."""
        sentences = re.split(r"(?<=[。！？.!?])\s*", text)
        chunks: list[str] = []
        buf = ""
        for sent in sentences:
            if len(buf) + len(sent) > self._max and buf:
                chunks.append(buf.strip())
                buf = sent
            else:
                buf += " " + sent if buf else sent
        if buf.strip():
            chunks.append(buf.strip())
        return chunks

    # ---- fixed strategy ----

    def _chunk_fixed(self, doc_id: str, text: str) -> list[tuple[str, str]]:
        chunks: list[tuple[str, str]] = []
        start = 0
        idx = 0
        while start < len(text):
            end = min(start + self._max, len(text))
            # Try to break at sentence boundary
            if end < len(text):
                boundary = max(
                    text.rfind("。", start, end),
                    text.rfind("！", start, end),
                    text.rfind("？", start, end),
                    text.rfind(". ", start, end),
                    text.rfind("! ", start, end),
                    text.rfind("? ", start, end),
                    text.rfind("\n", start, end),
                )
                if boundary > start + self._max // 2:
                    end = boundary + 1
            chunk_text = text[start:end].strip()
            if chunk_text:
                chunks.append((f"{doc_id}#{idx}", chunk_text))
                idx += 1
            start = end - self._overlap if end < len(text) else len(text)
            if start >= len(text):
                break
        return chunks
