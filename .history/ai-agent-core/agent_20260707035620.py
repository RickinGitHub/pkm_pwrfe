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
        parts = query.split(maxsplit=1)
        actual_query = parts[1].strip() if len(parts) == 2 else query
        if name == "file_search":
            return self._mcp.call(name, {"op": "search", "pattern": actual_query})
        return self._mcp.call(name, {"op": "lookup", "query": actual_query})

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
    from mcp.servers.knowledge_server import KnowledgeServer
    from mcp.servers.hybrid_knowledge_server import HybridKnowledgeServer
    from mcp.servers.file_search_server import FileSearchServer
    agent.register_skill("math_logic", MathLogic())
    agent.register_skill("file_ops", FileOps())
    agent.register_skill("fetch_web", FetchWebToMd())
    agent.register_mcp("knowledge", KnowledgeServer("rag/corpus"))
    agent.register_mcp("hybrid_knowledge", HybridKnowledgeServer("rag/corpus"))
    agent.register_mcp("file_search", FileSearchServer())
    query = " ".join(sys.argv[1:]) or "calc 2 + 2"
    out = agent.handle(query)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
