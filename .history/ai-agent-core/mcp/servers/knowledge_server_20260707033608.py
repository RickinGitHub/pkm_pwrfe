from pathlib import Path
from rank_bm25 import BM25Okapi


def _tokenize(text: str) -> list[str]:
    return text.lower().split()


class KnowledgeServer:
    def __init__(self, corpus_dir: str):
        self._dir = Path(corpus_dir)
        self._docs: list[tuple[str, str]] = []
        self._load()

    def _load(self) -> None:
        if not self._dir.exists():
            return
        for p in sorted(self._dir.rglob("*.txt")):
            if p.is_file():
                self._docs.append((str(p.relative_to(self._dir)), p.read_text(encoding="utf-8")))
        for p in sorted(self._dir.rglob("*.md")):
            if p.is_file():
                self._docs.append((str(p.relative_to(self._dir)), p.read_text(encoding="utf-8")))

    def execute(self, args: dict) -> dict:
        op = args.get("op")
        if op != "lookup":
            return {"ok": False, "result": None, "error": f"unknown op: {op}"}
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            return {"ok": False, "result": None, "error": "missing or empty 'query'"}
        q_lower = query.lower()
        for name, text in self._docs:
            if q_lower in text.lower():
                return {"ok": True, "result": text, "error": None}
        if not self._docs:
            return {"ok": True, "result": "", "error": None}
        corpus = [_tokenize(t) for _, t in self._docs]
        bm25 = BM25Okapi(corpus)
        scores = bm25.get_scores(_tokenize(query))
        best = int(scores.argmax())
        if scores[best] <= 0:
            return {"ok": True, "result": "no match", "error": None}
        return {"ok": True, "result": self._docs[best][1], "error": None}
