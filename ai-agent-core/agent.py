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
            ("project", "skills", "math_logic, file_ops, fetch_web, context, find_ops, grep_ops, tree_ops, pipeline_ops"),
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
        """Route knowledge queries: reload, filter, list, tags, chunks, or lookup (CN/EN)."""
        low = query.strip().lower()

        # "reload" → op=reload (re-scan corpus, rebuild all indexes)
        if low in ("reload", "reload index", "reload corpus", "rebuild index"):
            return self._mcp.call("knowledge", {"op": "reload"})

        # "chunks <path>" → op=chunks (Phase 7)
        if low.startswith("chunks ") or low == "chunks":
            path = query[len("chunks"):].strip()
            if not path:
                return {"ok": False, "result": None,
                        "error": "chunks requires a path, e.g. 'chunks rag/corpus/foo.md'"}
            return self._mcp.call("knowledge", {"op": "chunks", "path": path})

        # "chunks_by_cat l1 [l2] [l3]" → op=chunks_by_cat (Phase 7)
        if low.startswith("chunks_by_cat"):
            parts = query[len("chunks_by_cat"):].strip().split()
            args: dict = {"op": "chunks_by_cat"}
            if len(parts) >= 1:
                args["l1"] = parts[0]
            if len(parts) >= 2:
                args["l2"] = parts[1]
            if len(parts) >= 3:
                args["l3"] = parts[2]
            if "l1" not in args:
                return {"ok": False, "result": None,
                        "error": "chunks_by_cat requires l1, e.g. 'chunks_by_cat 科技 AI 模型'"}
            return self._mcp.call("knowledge", args)

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
            return self._parse_fetch_args(text)
        if low.startswith("reflect"):
            return {"op": "reflect", "raw_query": text}
        if low.startswith("find_grep "):
            return self._parse_pipeline_args(text)
        if low.startswith(("build ", "rebuild ", "update ")):
            return self._parse_build_similarity_args(text)
        if low.startswith(("ingest ", "pipeline ", "reindex ")):
            path = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) == 2 else ""
            return {"op": "ingest", "path": path} if path else {"op": "ingest"}
        if low.startswith(("unindex ", "delete index ", "delete_index ", "remove index ", "remove_index ")):
            path = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) == 2 else ""
            return {"op": "unindex", "path": path} if path else {"op": "unindex"}
        if low.startswith("find "):
            return self._parse_find_args(text)
        if low.startswith("grep "):
            return self._parse_grep_args(text)
        if low.startswith("tree "):
            return self._parse_tree_args(text)
        if low.startswith(("review", "evolve")):
            # review [l1] [l2] [l3] [--query "..."] [--max-chars N] [--dry-run]
            parts = text.split()
            # 第一个 token 是 review/evolve，剩下最多取前 3 个作为 l1/l2/l3
            rest = parts[1:] if len(parts) > 1 else []
            args: dict = {"op": "review"}
            l1 = l2 = l3 = None
            i = 0
            while i < len(rest):
                tok = rest[i]
                if tok == "--query":
                    # 取后续所有作为 query
                    args["query"] = " ".join(rest[i + 1:])
                    i = len(rest)
                elif tok == "--max-chars":
                    if i + 1 < len(rest):
                        args["max_chars"] = int(rest[i + 1])
                        i += 2
                    else:
                        i += 1
                elif tok == "--dry-run":
                    args["dry_run"] = True
                    i += 1
                elif tok == "--no-cache":
                    args["use_cache"] = False
                    i += 1
                else:
                    # 按位置填 l1/l2/l3
                    if l1 is None:
                        l1 = tok
                    elif l2 is None:
                        l2 = tok
                    elif l3 is None:
                        l3 = tok
                    i += 1
            if l1:
                args["l1"] = l1
            if l2:
                args["l2"] = l2
            if l3:
                args["l3"] = l3
            return args
        return {"op": "read", "path": text}

    @staticmethod
    def _parse_find_args(text: str) -> dict:
        """`find <path> [-name X] [-type f|d] [-maxdepth N] [-recursive]`"""
        parts = text.split()
        args: dict = {"op": "find"}
        path = None
        i = 1
        while i < len(parts):
            tok = parts[i]
            if tok == "-name":
                if i + 1 < len(parts):
                    args["name"] = parts[i + 1]; i += 2
                else:
                    i += 1
            elif tok == "-regex":
                if i + 1 < len(parts):
                    args["regex"] = parts[i + 1]; i += 2
                else:
                    i += 1
            elif tok == "-type":
                if i + 1 < len(parts):
                    args["type"] = parts[i + 1]; i += 2
                else:
                    i += 1
            elif tok == "-maxdepth":
                if i + 1 < len(parts):
                    args["max_depth"] = int(parts[i + 1]); i += 2
                else:
                    i += 1
            elif tok in ("-recursive", "--recursive"):
                args["recursive"] = True; i += 1
            elif tok == "-empty":
                args["empty"] = True; i += 1
            elif tok.startswith("-size"):
                # -size +1M / -size -100k 简化处理: 仅取数字
                if len(tok) > 5:
                    args["min_size"] = int("".join(c for c in tok[5:] if c.isdigit()) or 0)
                i += 1
            elif tok.startswith("-mtime"):
                # -mtime -7 → modified_within_days
                if len(tok) > 6:
                    val = "".join(c for c in tok[6:] if c.isdigit())
                    if val:
                        args["modified_within_days"] = int(val)
                i += 1
            elif not tok.startswith("-") and path is None:
                path = tok; i += 1
            else:
                i += 1
        args["path"] = path or "."
        return args

    @staticmethod
    def _parse_grep_args(text: str) -> dict:
        """`grep <pattern> [path] [-i] [-n] [-r] [-l] [-c] [-v] [-E]`"""
        import shlex
        try:
            parts = shlex.split(text)
        except ValueError:
            parts = text.split()
        args: dict = {"op": "search"}
        positional: list[str] = []
        i = 1
        while i < len(parts):
            tok = parts[i]
            if tok in ("-i", "--ignore-case"):
                args["ignore_case"] = True
            elif tok in ("-n", "--line-number"):
                args["line_number"] = True
            elif tok in ("-r", "-R", "--recursive"):
                args["recursive"] = True
            elif tok in ("-l", "--files-with-matches"):
                args["files_with_matches"] = True
            elif tok in ("-c", "--count"):
                args["count"] = True
            elif tok in ("-v", "--invert-match"):
                args["invert"] = True
            elif tok in ("-E", "--extended-regexp"):
                args["use_regex"] = True
            elif tok in ("-C", "--context"):
                if i + 1 < len(parts):
                    n = int(parts[i + 1]); args["context_before"] = n; args["context_after"] = n; i += 2
                    continue
            elif tok in ("-A", "--after-context"):
                if i + 1 < len(parts):
                    args["context_after"] = int(parts[i + 1]); i += 2
                    continue
            elif tok in ("-B", "--before-context"):
                if i + 1 < len(parts):
                    args["context_before"] = int(parts[i + 1]); i += 2
                    continue
            elif tok in ("-g", "--glob"):
                if i + 1 < len(parts):
                    args["glob"] = parts[i + 1]; i += 2
                    continue
            elif tok in ("-m", "--max-count"):
                if i + 1 < len(parts):
                    args["max_count"] = int(parts[i + 1]); i += 2
                    continue
            elif tok.startswith("-"):
                i += 1
                continue
            else:
                positional.append(tok)
            i += 1
        if not positional:
            return {"op": "search", "_error": "missing pattern"}
        args["pattern"] = positional[0]
        if len(positional) >= 2:
            args["path"] = positional[1]
        else:
            args["path"] = "."
        return args

    @staticmethod
    def _parse_tree_args(text: str) -> dict:
        """`tree [path] [-L N] [-d] [-a] [-s] [-h] [-f] [-P pat] [-I pat] [--noreport]`"""
        parts = text.split()
        args: dict = {"op": "tree"}
        path = None
        i = 1
        while i < len(parts):
            tok = parts[i]
            if tok == "-L" and i + 1 < len(parts):
                args["max_depth"] = int(parts[i + 1]); i += 2
            elif tok == "-P" and i + 1 < len(parts):
                args["pattern"] = parts[i + 1]; i += 2
            elif tok == "-I" and i + 1 < len(parts):
                args["ignore"] = parts[i + 1]; i += 2
            elif tok == "-d":
                args["dirs_only"] = True; i += 1
            elif tok == "-a":
                args["all_files"] = True; i += 1
            elif tok == "-s":
                args["show_size"] = True; i += 1
            elif tok == "-h":
                args["human_size"] = True; args["show_size"] = True; i += 1
            elif tok == "-f":
                args["full_path"] = True; i += 1
            elif tok == "--noreport":
                args["noreport"] = True; i += 1
            elif tok.startswith("-") and tok not in ("-d", "-a", "-s", "-h", "-f"):
                # 兼容 -aL2 这种合并短选项
                compact = tok[1:]
                j = 0
                while j < len(compact):
                    c = compact[j]
                    if c == "d": args["dirs_only"] = True
                    elif c == "a": args["all_files"] = True
                    elif c == "s": args["show_size"] = True
                    elif c == "h": args["human_size"] = True; args["show_size"] = True
                    elif c == "f": args["full_path"] = True
                    elif c == "L" and j + 1 < len(compact):
                        args["max_depth"] = int(compact[j + 1:]); break
                    elif c == "P" and j + 1 < len(compact):
                        args["pattern"] = compact[j + 1:]; break
                    elif c == "I" and j + 1 < len(compact):
                        args["ignore"] = compact[j + 1:]; break
                    j += 1
                i += 1
            elif not tok.startswith("-") and path is None:
                path = tok; i += 1
            else:
                i += 1
        args["path"] = path or "."
        return args

    @staticmethod
    def _parse_pipeline_args(text: str) -> dict:
        """`find_grep <path> --name "*.py" --pattern TODO [-r] [-i] [-n] [--regex]`"""
        parts = text.split()
        args: dict = {"op": "find_grep"}
        path = None
        i = 1
        while i < len(parts):
            tok = parts[i]
            if tok in ("--name", "--find-name") and i + 1 < len(parts):
                args["find_name"] = parts[i + 1]; i += 2
            elif tok in ("--regex", "--find-regex") and i + 1 < len(parts):
                args["find_regex"] = parts[i + 1]; i += 2
            elif tok == "--type" and i + 1 < len(parts):
                args["find_type"] = parts[i + 1]; i += 2
            elif tok in ("-r", "--recursive"):
                args["find_recursive"] = True; i += 1
            elif tok == "--max-depth" and i + 1 < len(parts):
                args["find_max_depth"] = int(parts[i + 1]); i += 2
            elif tok == "--min-size" and i + 1 < len(parts):
                args["find_min_size"] = int(parts[i + 1]); i += 2
            elif tok == "--mtime" and i + 1 < len(parts):
                args["find_modified_within_days"] = int(parts[i + 1]); i += 2
            elif tok in ("-p", "--pattern") and i + 1 < len(parts):
                args["grep_pattern"] = parts[i + 1]; i += 2
            elif tok in ("-i", "--ignore-case"):
                args["grep_ignore_case"] = True; i += 1
            elif tok in ("-n", "--line-number"):
                args["grep_line_number"] = True; i += 1
            elif tok in ("-l", "--files-with-matches"):
                args["grep_files_with_matches"] = True; i += 1
            elif tok in ("-c", "--count"):
                args["grep_count"] = True; i += 1
            elif tok in ("-v", "--invert"):
                args["grep_invert"] = True; i += 1
            elif tok in ("-E", "--use-regex"):
                args["grep_use_regex"] = True; i += 1
            elif tok in ("-A", "--context-after") and i + 1 < len(parts):
                args["grep_context_after"] = int(parts[i + 1]); i += 2
            elif tok in ("-B", "--context-before") and i + 1 < len(parts):
                args["grep_context_before"] = int(parts[i + 1]); i += 2
            elif tok in ("-m", "--max-count") and i + 1 < len(parts):
                args["grep_max_count"] = int(parts[i + 1]); i += 2
            elif not tok.startswith("-") and path is None:
                path = tok; i += 1
            else:
                i += 1
        args["path"] = path or "."
        return args

    @staticmethod
    def _parse_build_similarity_args(text: str) -> dict:
        """`build similarity edges [--corpus <dir>] [--graph-db <path>] [--top-k N] [--min-score F] [--clear]`"""
        parts = text.split()
        args: dict = {"op": "build_similarity_edges"}
        i = 1
        while i < len(parts):
            tok = parts[i]
            if tok == "--corpus" and i + 1 < len(parts):
                args["corpus_dir"] = parts[i + 1]; i += 2
            elif tok == "--graph-db" and i + 1 < len(parts):
                args["graph_db"] = parts[i + 1]; i += 2
            elif tok == "--top-k" and i + 1 < len(parts):
                args["top_k"] = int(parts[i + 1]); i += 2
            elif tok == "--min-score" and i + 1 < len(parts):
                args["min_score"] = float(parts[i + 1]); i += 2
            elif tok == "--clear":
                args["clear"] = True; i += 1
            else:
                i += 1
        return args

    @staticmethod
    def _parse_fetch_args(text: str) -> dict:
        """`fetch <url> [--format md|json|html] [--save-img] [--save-attachments] [--links-only] [--timeout N] [--sync]`"""
        parts = text.split()
        args: dict = {"op": "fetch"}
        url = None
        i = 1
        while i < len(parts):
            tok = parts[i]
            if tok == "--format" and i + 1 < len(parts):
                args["format"] = parts[i + 1]; i += 2
            elif tok == "--save-img":
                args["save_img"] = True; i += 1
            elif tok == "--save-attachments":
                args["save_attachments"] = True; i += 1
            elif tok == "--links-only":
                args["links_only"] = True; i += 1
            elif tok == "--timeout" and i + 1 < len(parts):
                args["timeout"] = int(parts[i + 1]); i += 2
            elif tok == "--sync":
                args["sync"] = True; i += 1
            elif tok == "--force":
                args["force"] = True; i += 1
            elif not tok.startswith("-") and url is None:
                url = tok; i += 1
            else:
                i += 1
        if url:
            args["url"] = url
        return args

    def _call_llm(self, query: str, rules) -> dict:
        provider = os.environ.get("LLM_PROVIDER", "anthropic").strip().lower()
        if provider == "openai":
            return self._call_llm_openai(query, rules)
        return self._call_llm_anthropic(query, rules)

    def _call_llm_anthropic(self, query: str, rules) -> dict:
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
            messages = self._build_llm_messages(query, rules)
            resp = client.messages.create(
                model=model,
                max_tokens=rules.max_output_tokens,
                messages=messages,
            )
            text = "".join(block.text for block in resp.content if hasattr(block, "text"))
            return self._parse_llm_response(text)
        except Exception as e:
            return {"ok": False, "result": None, "error": f"{type(e).__name__}: {e}"}

    def _call_llm_openai(self, query: str, rules) -> dict:
        """Call an OpenAI-compatible API (DeepSeek, OpenAI, etc.)."""
        try:
            from openai import OpenAI
        except ImportError as e:
            return {"ok": False, "result": None, "error": f"openai sdk missing: {e}"}
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return {"ok": False, "result": None, "error": "OPENAI_API_KEY not set"}
        base_url = os.environ.get("OPENAI_BASE_URL", "https://api.deepseek.com").rstrip("/") + "/v1"
        model = os.environ.get("OPENAI_MODEL", "deepseek-chat")
        client = OpenAI(api_key=api_key, base_url=base_url)
        try:
            messages = self._build_llm_messages(query, rules)
            resp = client.chat.completions.create(
                model=model,
                max_tokens=rules.max_output_tokens,
                messages=messages,
            )
            text = resp.choices[0].message.content or ""
            return self._parse_llm_response(text)
        except Exception as e:
            return {"ok": False, "result": None, "error": f"{type(e).__name__}: {e}"}

    @staticmethod
    def _parse_llm_response(text: str) -> dict:
        """Try to parse LLM response as JSON; fall back to raw text."""
        try:
            parsed = json.loads(text)
            return {"ok": True, "result": parsed, "error": None}
        except json.JSONDecodeError:
            return {"ok": True, "result": text, "error": None}

    def _build_llm_messages(self, query: str, rules) -> list[dict]:
        """Compose multi-turn messages from short-term history + current query.

        P0-1: injects self._short.recent(10) so the LLM fallback sees context.
        The current query (already appended in handle()) is rewritten to include
        the system prompt prefix and JSON-only directive.
        """
        history = self._short.recent(10)
        messages: list[dict] = []
        for entry in history:
            role = entry.get("role")
            content = entry.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        current_prompt = f"{rules.prompt_prefix}\n\nUser query: {query}\nOutput JSON only."
        if messages and messages[-1]["role"] == "user" and messages[-1]["content"] == query:
            messages[-1] = {"role": "user", "content": current_prompt}
        else:
            messages.append({"role": "user", "content": current_prompt})
        return messages


def main() -> None:
    import sys
    from harness.factory import build_agent

    agent = build_agent()
    query = " ".join(sys.argv[1:]) or "calc 2 + 2"
    out = agent.handle(query)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
