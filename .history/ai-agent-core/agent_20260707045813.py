import os
import json
import re
from dotenv import load_dotenv

from config.loader import load_rules, load_routing
from harness.cache_guard import CacheGuard
from harness.evaluator import Evaluator
from memories.short_term import ShortTerm
from memories.long_term import LongTerm
from mcp.mcp_client import MCPClient
from skills.base import Skill


load_dotenv()


class AgentCore:
    def __init__(
        self,
        rules_path: str,
        routing_path: str,
        cache_path: str,
        short_term_path: str,
        long_term_path: str,
    ):
        self._rules = load_rules(rules_path)
        self._routing = load_routing(routing_path)
        self._cache = CacheGuard(cache_path)
        self._short = ShortTerm(short_term_path)
        self._long = LongTerm(long_term_path)
        self._eval = Evaluator(expected_format=self._rules.output_format)
        self._skills: dict[str, Skill] = {}
        self._mcp = MCPClient()

    def register_skill(self, name: str, skill: Skill) -> None:
        self._skills[name] = skill

    def register_mcp(self, name: str, tool) -> None:
        self._mcp.register(name, tool)

    def bootstrap_memory(self) -> int:
        """Write project metadata to long-term memory (idempotent).

        Returns number of facts written (0 if already bootstrapped).
        """
        existing = self._long.query(subject="project", predicate="name")
        if existing:
            return 0
        from datetime import datetime
        facts = [
            ("project", "name", "ai-agent-core"),
            ("project", "version", "0.1.0"),
            ("project", "description", "Token-efficient Agentic Core with deterministic-first routing"),
            ("project", "architecture", "cache → skills → MCP → LLM fallback"),
            ("project", "repo", "e:/workspace/pkg/ai-agent-core"),
            ("project", "last_boot", datetime.now().isoformat()),
            ("project", "skills", "math_logic, file_ops, fetch_web, context"),
            ("project", "mcp_servers", "knowledge, hybrid_knowledge, file_search"),
        ]
        for s, p, o in facts:
            self._long.add(s, p, o)
        return len(facts)

    def handle(self, query: str) -> dict:
        self._short.append("user", query)

        cached = self._cache.get(query)
        if cached is not None:
            self._short.append("assistant", json.dumps(cached, ensure_ascii=False))
            return cached

        result = self._route(query)

        if result.get("ok"):
            self._cache.set(query, result)
            self._short.append("assistant", json.dumps(result, ensure_ascii=False))
            self._long.add("user", "asked", query)
            self._long.add("assistant", "answered", json.dumps(result.get("result"), ensure_ascii=False))
        else:
            self._short.append("assistant", f"error: {result.get('error')}")

        return result

    def _route(self, query: str) -> dict:
        normalized = re.sub(r"\s+", " ", query.strip().lower())
        for entry in self._routing.entries:
            if re.match(entry.intent, normalized):
                if entry.tool_type == "skill":
                    out = self._call_skill(entry.tool_name, query)
                elif entry.tool_type == "mcp":
                    out = self._call_mcp(entry.tool_name, query)
                else:
                    out = self._call_llm(query, self._rules)
                validated = self._eval.validate(out)
                if validated.get("ok"):
                    return validated
                if entry.fallback == "llm":
                    fb = self._call_llm(query, self._rules)
                    return self._eval.validate(fb)
                return validated
        return {"ok": False, "result": None, "error": "no routing match"}

    def _call_skill(self, name: str, query: str) -> dict:
        skill = self._skills.get(name)
        if skill is None:
            return {"ok": False, "result": None, "error": f"unknown skill: {name}"}
        args = self._parse_skill_args(query)
        try:
            return skill.execute(args)
        except Exception as e:
            return {"ok": False, "result": None, "error": f"{type(e).__name__}: {e}"}

    def _call_mcp(self, name: str, query: str) -> dict:
        if name == "file_search":
            pattern = self._extract_file_pattern(query)
            return self._mcp.call(name, {"op": "search", "pattern": pattern})
        # knowledge server: route to correct op based on query prefix
        if name == "knowledge":
            return self._call_knowledge(query)
        parts = query.split(maxsplit=1)
        actual_query = parts[1].strip() if len(parts) == 2 else query
        return self._mcp.call(name, {"op": "lookup", "query": actual_query})

    def _call_knowledge(self, query: str) -> dict:
        """Route knowledge queries: filter, list, tags, or lookup (CN/EN)."""
        low = query.strip().lower()

        # "filter [精华] [职场]" → op=filter
        if low.startswith("filter"):
            import re
            tags = re.findall(r'\[([^\]]+)\]', query)
            if tags:
                return self._mcp.call("knowledge", {"op": "filter", "tags": tags})
            rest = query[6:].strip()
            if rest:
                return self._mcp.call("knowledge", {"op": "filter", "tags": rest})
            return {"ok": False, "result": None, "error": "filter requires tags, e.g. 'filter [精华] [职场]'"}

        # "list" / "列出" / "所有" → op=list
        if low in ("list", "list all", "list docs") or low.startswith(("列出", "所有")):
            return self._mcp.call("knowledge", {"op": "list"})

        # "tags" / "标签" → op=tags
        if low in ("tags", "show tags", "list tags") or low.startswith("标签"):
            return self._mcp.call("knowledge", {"op": "tags"})

        # Chinese NL → strip prefix verbs, extract keywords
        cn_prefixes = [
            "查询", "搜索", "查找", "寻找", "找", "帮我", "什么是",
            "怎么", "如何", "有没有", "是否有",
        ]
        actual_query = query
        for pf in cn_prefixes:
            if low.startswith(pf):
                # Also strip trailing particles: 的, 一下, 吗, 呢, ?
                rest = query[len(pf):].strip()
                actual_query = rest.rstrip("的吗呢？?！! 一下").strip()
                if not actual_query:
                    actual_query = rest
                break

        # EN lookup: strip verb prefix
        en_prefixes = ("lookup", "search", "find")
        for pf in en_prefixes:
            if low.startswith(pf):
                actual_query = query[len(pf):].strip()
                break

        return self._mcp.call("knowledge", {"op": "lookup", "query": actual_query})

    def _extract_file_pattern(self, query: str) -> str:
        """Extract glob pattern from file search query.

        Strips known verb prefixes like 'find files', 'ls', 'dir', 'glob', etc.
        """
        low = query.strip().lower()
        for prefix in ("find files ", "find file ", "file search ", "file.search ",
                       "ls ", "dir ", "glob "):
            if low.startswith(prefix):
                return query[len(prefix):].strip()
        # fallback: take last space-separated token as pattern
        parts = query.strip().split()
        return parts[-1] if len(parts) > 1 else query.strip()

    def _parse_skill_args(self, query: str) -> dict:
        text = query.strip()
        low = text.lower()
        if low.startswith("calc"):
            return {"op": "calc", "expr": text[4:].strip()}
        if low.startswith("stats"):
            nums_part = text[5:].strip()
            try:
                values = [float(x) for x in nums_part.split(",")]
            except ValueError:
                return {"op": "stats", "values": []}
            return {"op": "stats", "values": values}
        if low.startswith(("context", "brief", "resume", "status", "whoami")):
            return {"op": "context"}
        for prefix in ("read", "load", "show", "clean", "sanitize"):
            if low.startswith(prefix):
                rest = text[len(prefix):].strip()
                tokens = rest.split(maxsplit=1)
                if tokens and tokens[0].lower() == "file":
                    rest = tokens[1].strip() if len(tokens) == 2 else ""
                op = "clean" if prefix in ("clean", "sanitize") else "read"
                return {"op": op, "path": rest} if rest else {"op": op}
        if low.startswith(("fetch", "crawl")):
            rest = text.split(maxsplit=1)
            url = rest[1].strip() if len(rest) == 2 else ""
            return {"op": "fetch", "url": url} if url else {"op": "fetch"}
        return {"op": "read", "path": text}

    def _call_llm(self, query: str, rules) -> dict:
        try:
            import anthropic
        except ImportError as e:
            return {"ok": False, "result": None, "error": f"anthropic sdk missing: {e}"}
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return {"ok": False, "result": None, "error": "ANTHROPIC_API_KEY not set"}
        client = anthropic.Anthropic(api_key=api_key)
        model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-5-20250929")
        prompt = f"{rules.prompt_prefix}\n\nUser query: {query}\nOutput JSON only."
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=rules.max_output_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(block.text for block in resp.content if hasattr(block, "text"))
            try:
                parsed = json.loads(text)
                return {"ok": True, "result": parsed, "error": None}
            except json.JSONDecodeError:
                return {"ok": True, "result": text, "error": None}
        except Exception as e:
            return {"ok": False, "result": None, "error": f"{type(e).__name__}: {e}"}


def main() -> None:
    import sys
    agent = AgentCore(
        rules_path=os.environ.get("RULES_CONFIG", "config/rules.yaml"),
        routing_path=os.environ.get("ROUTING_CONFIG", "config/routing.yaml"),
        cache_path=os.environ.get("CACHE_PATH", "memories/cache.db"),
        short_term_path=os.environ.get("SHORT_TERM_PATH", "memories/short_term.json"),
        long_term_path=os.environ.get("LONG_TERM_DB_PATH", "memories/long_term.db"),
    )
    from skills.file_ops import FileOps
    from skills.math_logic import MathLogic
    from skills.fetch_web_to_md import FetchWebToMd
    from skills.context import ContextSkill
    from mcp.servers.knowledge_server import KnowledgeServer
    from mcp.servers.hybrid_knowledge_server import HybridKnowledgeServer
    from mcp.servers.file_search_server import FileSearchServer
    from rag.corpus_loader import CorpusLoader
    from rag.metadata import MetadataIndex
    from rag.embedder import get_embedder

    # ---- chunking config ----
    chunk_enabled = os.environ.get("CORPUS_CHUNK_ENABLED", "1").lower() in ("1", "true", "yes")
    chunk_size = int(os.environ.get("CORPUS_CHUNK_SIZE", "1200"))
    chunk_overlap = int(os.environ.get("CORPUS_CHUNK_OVERLAP", "150"))

    # Dual loaders: knowledge uses full docs (fast), hybrid uses chunks (precise)
    corpus_loader = CorpusLoader("rag/corpus", chunk=False)
    corpus_loader_chunked = CorpusLoader(
        "rag/corpus", chunk=chunk_enabled,
        chunk_size=chunk_size, chunk_overlap=chunk_overlap,
    ) if chunk_enabled else corpus_loader

    # Shared metadata index — single source of truth for tags/dates/sources
    metadata = MetadataIndex("rag/corpus")
    metadata.build()

    # Embedder: uses EMBEDDING_MODEL env var or falls back to pseudo
    embedder = get_embedder()

    agent.register_skill("math_logic", MathLogic())
    agent.register_skill("file_ops", FileOps())
    agent.register_skill("fetch_web", FetchWebToMd())
    agent.register_skill("context", ContextSkill())
    agent.register_mcp("knowledge", KnowledgeServer(corpus_loader, metadata=metadata))
    agent.register_mcp(
        "hybrid_knowledge",
        HybridKnowledgeServer(corpus_loader_chunked, embedder=embedder),
    )
    agent.register_mcp("file_search", FileSearchServer())

    # Bootstrap project metadata into long-term memory (idempotent)
    agent.bootstrap_memory()
    query = " ".join(sys.argv[1:]) or "calc 2 + 2"
    out = agent.handle(query)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
