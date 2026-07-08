"""Context Resume Skill — rebuild project awareness from memories.

Reads long-term memory (project metadata, known facts) and short-term memory
(recent conversation turns) to produce a structured project brief.

New chat session? Just run:  python -m agent "context"
"""

import json
import os
from datetime import datetime

from memories.long_term import LongTerm
from memories.short_term import ShortTerm


class ContextSkill:
    """Skill that summarizes agent memories into a ready-to-use project brief.

    Accepts args:
        op: "context" | "brief" | "resume" | "status"
        long_term_path: optional override (default from env LONG_TERM_DB_PATH)
        short_term_path: optional override (default from env SHORT_TERM_PATH)
        recent_n: number of recent conversation turns to include (default 10)
    """

    def execute(self, args: dict) -> dict:
        op = args.get("op", "context")
        if op not in ("context", "brief", "resume", "status"):
            return {"ok": False, "result": None, "error": f"unknown op: {op}"}

        lt_path = args.get("long_term_path") or os.environ.get(
            "LONG_TERM_DB_PATH", "memories/long_term.db"
        )
        st_path = args.get("short_term_path") or os.environ.get(
            "SHORT_TERM_PATH", "memories/short_term.json"
        )
        recent_n = int(args.get("recent_n", 10))

        brief = self._build_brief(lt_path, st_path, recent_n)
        return {"ok": True, "result": brief, "error": None}

    def _build_brief(self, lt_path: str, st_path: str, recent_n: int) -> dict:
        lt = LongTerm(lt_path)
        st = ShortTerm(st_path)

        # ---- project metadata ----
        meta: dict[str, str] = {}
        for subj, pred, obj in lt.query():
            if subj == "project":
                meta[pred] = obj

        # ---- recent facts ----
        facts = [
            f"{s} {p} {o}"
            for s, p, o in lt.query()
            if s not in ("project", "user", "assistant")
        ]

        # ---- recent conversation ----
        conv = st.recent(recent_n)
        history = [
            {
                "role": t["role"],
                "content": t["content"][:300],
                "ts": datetime.fromtimestamp(t["ts"]).isoformat() if "ts" in t else "",
            }
            for t in conv
        ]

        # ---- structured brief ----
        brief = {
            "project": {
                "name": meta.get("name", "unknown"),
                "version": meta.get("version", "unknown"),
                "description": meta.get("description", ""),
                "last_boot": meta.get("last_boot", ""),
                "total_facts": len(facts),
            },
            "recent_conversation": history,
            "known_facts": facts[-20:],  # most recent 20
            "summary": self._summarize(meta, conv, facts),
        }

        lt.close()
        return brief

    def _summarize(
        self,
        meta: dict[str, str],
        conv: list[dict],
        facts: list[str],
    ) -> str:
        lines = [
            f"# {meta.get('name', 'Project')} v{meta.get('version', '?')}",
            f"  {meta.get('description', '')}",
            f"  最后启动: {meta.get('last_boot', '首次')}",
            f"  已记录事实: {len(facts)} 条",
            "",
        ]
        if conv:
            lines.append(f"## 最近 {len(conv)} 轮对话")
            for t in conv[-5:]:
                role = t["role"]
                preview = t["content"][:120].replace("\n", " ")
                lines.append(f"  [{role}] {preview}")
            lines.append("")
        if facts:
            lines.append(f"## 已知事实 ({len(facts)} 条)")
            for f in facts[-10:]:
                lines.append(f"  - {f[:150]}")
        return "\n".join(lines)
