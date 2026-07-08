"""Review/Evolve Skill — Phase 5 双轨检索的"大跨度复盘"模式。

按 L1/L2/L3 分类批量打包全量文档，调 LLM（Gemini / Claude）做跨时空审计。

工作流：
    python -m agent "review 历史 中国 朝代"
      → GraphIndex.list_paths(l1='历史', l2='中国', l3='朝代')
      → 读取每个 path 的清洗后文本
      → 拼接成大 context（受 max_tokens 限流）
      → 调 LLM 做"认知审计"prompt
      → 缓存 review 结果（同 domain+query 24h 内复用）

与 quick/lookup 的区别：
    - lookup: FTS5 + BM25 返回 top-K snippet（毫秒级，省 token）
    - review: 按分类全量打包（秒级，烧 token，适合周末静思）
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

import yaml

from rag.graph_index import GraphIndex


_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
_DEFAULT_GRAPH_DB = _PROJECT_ROOT / "rag" / "graph_index.db"
_DEFAULT_CACHE_DB = _PROJECT_ROOT / "memories" / "review_cache.db"

# 默认 token 预算（按 ~4 char/token 估算）
_DEFAULT_MAX_CHARS = 400_000  # ~100k tokens，Gemini 1M context 的安全边界

_REVIEW_PROMPT_TEMPLATE = """你是个人知识库的认知审计员。下面是用户在「{domain}」领域积累的全部蒸馏文档（共 {n_docs} 篇）。

请基于这些文档，完成以下四项任务：

1. **核心观点梳理**：提炼用户在该领域的主要认知脉络（5-10 条）。
2. **逻辑盲区识别**：指出用户笔记中可能的认知偏差、未深究的假设、前后矛盾的观点。
3. **跨文档关联**：找出不同文档间潜在的主题关联、时间演进、因果链。
4. **实践建议**：基于上述分析，给出 3 条可落地的实践建议，帮助用户深化认知。

文档清单：
{docs}

请用 Markdown 格式输出审计报告，不要复述原文，要给出洞察。
"""


class ReviewSkill:
    """Phase 5: 双轨检索的 review/evolve 模式。

    按分类打包全量文档调 LLM 做大跨度复盘。

    Args (execute):
        op: "review" | "evolve"
        l1, l2, l3: 分类筛选（任一可选，至少提供一个）
        query: 可选的聚焦问题（注入到 prompt）
        max_chars: token 预算上限（默认 400k chars ≈ 100k tokens）
        use_cache: 是否使用 24h 缓存（默认 True）
        dry_run: 仅返回打包的 context，不调 LLM（默认 False，调试用）
    """

    def execute(self, args: dict) -> dict:
        op = args.get("op", "review")
        if op not in ("review", "evolve"):
            return {"ok": False, "result": None, "error": f"unknown op: {op}"}

        l1 = args.get("l1")
        l2 = args.get("l2")
        l3 = args.get("l3")
        if not any([l1, l2, l3]):
            return {"ok": False, "result": None, "error": "at least one of l1/l2/l3 required"}

        max_chars = int(args.get("max_chars", _DEFAULT_MAX_CHARS))
        use_cache = bool(args.get("use_cache", True))
        dry_run = bool(args.get("dry_run", False))
        query = args.get("query")

        graph_db = Path(args.get("graph_db_path") or os.environ.get(
            "GRAPH_DB_PATH", _DEFAULT_GRAPH_DB))
        if not graph_db.exists():
            return {"ok": False, "result": None, "error": f"graph db not found: {graph_db}"}

        # 缓存 DB 路径（可被 args 覆盖，便于测试隔离）
        cache_db = Path(args.get("cache_db_path") or os.environ.get(
            "REVIEW_CACHE_DB", _DEFAULT_CACHE_DB))

        # 1. 从 graph_index 按 l1/l2/l3 拉取所有 path
        try:
            gi = GraphIndex(str(graph_db))
            try:
                paths = gi.list_paths(l1=l1, l2=l2, l3=l3)
            finally:
                gi.close()
        except sqlite3.Error as e:
            return {"ok": False, "result": None, "error": f"graph_index query failed: {e}"}

        if not paths:
            return {"ok": True, "result": {"domain": {"l1": l1, "l2": l2, "l3": l3},
                                            "n_docs": 0, "report": "no docs in this domain"},
                    "error": None}

        # 2. 读取每个 path 的清洗后文本，拼接成大 context（受 max_chars 限流）
        docs_text, truncated = self._assemble_docs(paths, max_chars)

        # 3. dry_run 模式：仅返回打包的 context，不调 LLM
        if dry_run:
            return {
                "ok": True,
                "result": {
                    "domain": {"l1": l1, "l2": l2, "l3": l3},
                    "n_docs": len(paths),
                    "truncated": truncated,
                    "chars": len(docs_text),
                    "context": docs_text,
                },
                "error": None,
            }

        # 4. 检查缓存
        domain_key = f"{l1 or '*'}/{l2 or '*'}/{l3 or '*'}"
        cache_key = self._cache_key(domain_key, query)
        if use_cache:
            cached = self._cache_get(cache_key, cache_db)
            if cached is not None:
                return {"ok": True, "result": {"domain": {"l1": l1, "l2": l2, "l3": l3},
                                                "n_docs": len(paths), "truncated": truncated,
                                                "cached": True, "report": cached},
                        "error": None}

        # 5. 调 LLM
        prompt = _REVIEW_PROMPT_TEMPLATE.format(
            domain=domain_key, n_docs=len(paths), docs=docs_text,
        )
        if query:
            prompt = f"用户聚焦问题：{query}\n\n{prompt}"

        llm_out = self._call_llm(prompt)
        if not llm_out["ok"]:
            return llm_out

        report = llm_out["result"]

        # 6. 写缓存
        if use_cache:
            self._cache_set(cache_key, report, cache_db)

        return {
            "ok": True,
            "result": {
                "domain": {"l1": l1, "l2": l2, "l3": l3},
                "n_docs": len(paths),
                "truncated": truncated,
                "chars": len(docs_text),
                "cached": False,
                "report": report,
            },
            "error": None,
        }

    # ---- helpers ----

    def _assemble_docs(self, paths: list[str], max_chars: int) -> tuple[str, bool]:
        """读取并拼接文档，受 max_chars 限流。Returns (text, truncated)."""
        parts: list[str] = []
        total = 0
        truncated = False
        for p in paths:
            try:
                content = Path(p).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            # 单篇文档头：路径 + 分隔线
            header = f"\n\n## [{Path(p).name}]\n"
            chunk = header + content
            if total + len(chunk) > max_chars:
                # 截断到 max_chars
                remaining = max_chars - total
                if remaining > 200:  # 至少留 200 字才截断
                    parts.append(chunk[:remaining])
                    parts.append("\n\n[...truncated due to token budget...]")
                else:
                    parts.append("\n\n[...more docs omitted due to token budget...]")
                truncated = True
                break
            parts.append(chunk)
            total += len(chunk)
        return "".join(parts), truncated

    def _cache_key(self, domain_key: str, query: str | None) -> str:
        raw = f"{domain_key}|{query or ''}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _cache_get(self, key: str, cache_db: Path) -> str | None:
        if not cache_db.exists():
            return None
        try:
            import sqlite3 as sq
            conn = sq.connect(str(cache_db))
            cur = conn.execute(
                "SELECT report, ts FROM review_cache WHERE key = ?", (key,),
            )
            row = cur.fetchone()
            conn.close()
            if row is None:
                return None
            # 24h TTL
            if time.time() - float(row[1]) > 86400:
                return None
            return row[0]
        except sqlite3.Error:
            return None

    def _cache_set(self, key: str, report: str, cache_db: Path) -> None:
        try:
            import sqlite3 as sq
            cache_db.parent.mkdir(parents=True, exist_ok=True)
            conn = sq.connect(str(cache_db))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS review_cache (
                    key TEXT PRIMARY KEY,
                    report TEXT NOT NULL,
                    ts REAL NOT NULL
                )
            """)
            conn.execute(
                "INSERT OR REPLACE INTO review_cache(key, report, ts) VALUES (?, ?, ?)",
                (key, report, time.time()),
            )
            conn.commit()
            conn.close()
        except sqlite3.Error:
            pass  # cache failure is non-fatal

    def _call_llm(self, prompt: str) -> dict:
        """Call Anthropic API. Returns envelope."""
        try:
            import anthropic
        except ImportError as e:
            return {"ok": False, "result": None, "error": f"anthropic sdk missing: {e}"}
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return {"ok": False, "result": None, "error": "ANTHROPIC_API_KEY not set"}
        client = anthropic.Anthropic(api_key=api_key)
        model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-5-20250929")
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=8192,
                messages=[{"role": "user", "content": prompt}],
            )
            # SDK 返回 content blocks，仅 TextBlock 有 .text 属性
            parts: list[str] = []
            for block in resp.content:
                if hasattr(block, "text") and isinstance(getattr(block, "text", None), str):
                    parts.append(block.text)
            text = "".join(parts)
            return {"ok": True, "result": text, "error": None}
        except Exception as e:
            return {"ok": False, "result": None, "error": f"{type(e).__name__}: {e}"}
