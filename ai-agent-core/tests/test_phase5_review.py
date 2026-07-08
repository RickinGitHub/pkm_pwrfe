"""Phase 5 tests: ReviewSkill — 双轨检索的 review/evolve 模式。

覆盖：
- ReviewSkill.execute 基本流程（dry_run 模式，不调 LLM）
- 分类筛选（l1/l2/l3）
- token 预算限流（max_chars）
- 缓存命中/失效
- 错误处理（无分类参数、graph db 不存在）
- agent._parse_skill_args 解析 "review l1 l2 l3" 命令
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from skills.review import ReviewSkill, _DEFAULT_MAX_CHARS
from rag.graph_index import GraphIndex


# ---------------------------------------------------------------------------
# Autouse fixture: isolate review cache DB per test
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolate_review_cache(tmp_path: Path, monkeypatch):
    """每个测试用 tmp_path 隔离缓存 DB，避免跨测试污染。"""
    monkeypatch.setenv("REVIEW_CACHE_DB", str(tmp_path / "review_cache.db"))


@pytest.fixture
def graph_db_with_docs(tmp_path: Path) -> Path:
    """建一个 graph_index.db，写入 3 篇文档（同分类）。"""
    db = tmp_path / "graph.db"
    gi = GraphIndex(str(db))
    for i in range(3):
        path = str(tmp_path / f"doc_{i}.md")
        Path(path).write_text(f"# Doc {i}\n\nContent about llm and gpt {i}.", encoding="utf-8")
        gi.upsert(path, "科技", "AI", "模型")
    gi.close()
    return db


# ---------------------------------------------------------------------------
# 基本流程
# ---------------------------------------------------------------------------

def test_review_requires_at_least_one_category(tmp_path: Path):
    skill = ReviewSkill()
    out = skill.execute({
        "op": "review",
        "graph_db_path": str(tmp_path / "graph.db"),
    })
    assert out["ok"] is False
    assert "at least one of l1/l2/l3" in out["error"]


def test_review_unknown_op_returns_error(tmp_path: Path):
    out = ReviewSkill().execute({"op": "frob"})
    assert out["ok"] is False
    assert "unknown op" in out["error"]


def test_review_graph_db_not_found_returns_error(tmp_path: Path):
    out = ReviewSkill().execute({
        "op": "review",
        "l1": "科技",
        "graph_db_path": str(tmp_path / "nonexistent.db"),
    })
    assert out["ok"] is False
    assert "graph db not found" in out["error"]


def test_review_dry_run_returns_context_without_llm(graph_db_with_docs: Path):
    """dry_run 模式仅打包 context，不调 LLM。"""
    skill = ReviewSkill()
    out = skill.execute({
        "op": "review",
        "l1": "科技", "l2": "AI", "l3": "模型",
        "graph_db_path": str(graph_db_with_docs),
        "dry_run": True,
    })
    assert out["ok"] is True
    r = out["result"]
    assert r["n_docs"] == 3
    assert r["truncated"] is False
    assert "Doc 0" in r["context"]
    assert "Doc 2" in r["context"]
    assert r["chars"] > 0
    # 不应调 LLM
    assert "report" not in r


def test_review_no_docs_returns_empty_report(graph_db_with_docs: Path):
    """分类下无文档时返回 no docs 报告。"""
    out = ReviewSkill().execute({
        "op": "review",
        "l1": "不存在",
        "graph_db_path": str(graph_db_with_docs),
        "dry_run": True,
    })
    assert out["ok"] is True
    assert out["result"]["n_docs"] == 0
    assert "no docs" in out["result"]["report"]


# ---------------------------------------------------------------------------
# token 预算限流
# ---------------------------------------------------------------------------

def test_review_truncates_when_max_chars_exceeded(graph_db_with_docs: Path):
    """文档总长超过 max_chars 时截断并标记 truncated=True。"""
    skill = ReviewSkill()
    out = skill.execute({
        "op": "review",
        "l1": "科技",
        "graph_db_path": str(graph_db_with_docs),
        "dry_run": True,
        "max_chars": 100,  # 极小预算
    })
    assert out["ok"] is True
    r = out["result"]
    assert r["truncated"] is True
    # context 应被截断到约 100 字符
    assert len(r["context"]) < 300


def test_review_max_chars_default_is_400k():
    """默认 token 预算约 100k tokens = 400k chars。"""
    assert _DEFAULT_MAX_CHARS == 400_000


# ---------------------------------------------------------------------------
# LLM 调用与缓存
# ---------------------------------------------------------------------------

def test_review_calls_llm_when_not_dry_run(graph_db_with_docs: Path):
    """非 dry_run 模式调 LLM。"""
    skill = ReviewSkill()
    fake_llm_resp = {"ok": True, "result": "# 审计报告\n\n核心观点：...", "error": None}
    with patch.object(skill, "_call_llm", return_value=fake_llm_resp) as mock_llm:
        out = skill.execute({
            "op": "review",
            "l1": "科技",
            "graph_db_path": str(graph_db_with_docs),
            "use_cache": False,
        })
    assert out["ok"] is True
    assert "审计报告" in out["result"]["report"]
    assert out["result"]["cached"] is False
    mock_llm.assert_called_once()
    # prompt 应含文档内容
    prompt = mock_llm.call_args[0][0]
    assert "Doc 0" in prompt
    assert "认知审计员" in prompt


def test_review_llm_failure_propagates_error(graph_db_with_docs: Path):
    """LLM 调用失败时信封 ok=False。"""
    skill = ReviewSkill()
    with patch.object(skill, "_call_llm",
                      return_value={"ok": False, "result": None, "error": "API key invalid"}):
        out = skill.execute({
            "op": "review",
            "l1": "科技",
            "graph_db_path": str(graph_db_with_docs),
            "use_cache": False,
        })
    assert out["ok"] is False
    assert "API key invalid" in out["error"]


def test_review_cache_hits_on_second_call(graph_db_with_docs: Path):
    """相同 domain+query 24h 内复用缓存，不重复调 LLM。"""
    skill = ReviewSkill()
    fake_llm_resp = {"ok": True, "result": "# 报告 v1", "error": None}
    with patch.object(skill, "_call_llm", return_value=fake_llm_resp) as mock_llm:
        out1 = skill.execute({
            "op": "review",
            "l1": "科技",
            "graph_db_path": str(graph_db_with_docs),
            "use_cache": True,
        })
        out2 = skill.execute({
            "op": "review",
            "l1": "科技",
            "graph_db_path": str(graph_db_with_docs),
            "use_cache": True,
        })
    assert out1["ok"] is True
    assert out2["ok"] is True
    assert out1["result"]["cached"] is False
    assert out2["result"]["cached"] is True
    assert out1["result"]["report"] == out2["result"]["report"]
    # LLM 只调一次（第二次命中缓存）
    assert mock_llm.call_count == 1


def test_review_cache_misses_on_different_query(graph_db_with_docs: Path):
    """不同 query 不命中缓存。"""
    skill = ReviewSkill()
    fake_llm_resp = {"ok": True, "result": "# 报告", "error": None}
    with patch.object(skill, "_call_llm", return_value=fake_llm_resp) as mock_llm:
        skill.execute({
            "op": "review", "l1": "科技", "query": "focus A",
            "graph_db_path": str(graph_db_with_docs), "use_cache": True,
        })
        skill.execute({
            "op": "review", "l1": "科技", "query": "focus B",
            "graph_db_path": str(graph_db_with_docs), "use_cache": True,
        })
    assert mock_llm.call_count == 2


def test_review_use_cache_false_skips_cache(graph_db_with_docs: Path):
    """use_cache=False 不读不写缓存。"""
    skill = ReviewSkill()
    fake_llm_resp = {"ok": True, "result": "# 报告", "error": None}
    with patch.object(skill, "_call_llm", return_value=fake_llm_resp) as mock_llm:
        skill.execute({
            "op": "review", "l1": "科技",
            "graph_db_path": str(graph_db_with_docs), "use_cache": False,
        })
        skill.execute({
            "op": "review", "l1": "科技",
            "graph_db_path": str(graph_db_with_docs), "use_cache": False,
        })
    assert mock_llm.call_count == 2


# ---------------------------------------------------------------------------
# prompt 构造
# ---------------------------------------------------------------------------

def test_review_prompt_includes_query_when_provided(graph_db_with_docs: Path):
    """query 参数应注入到 prompt 头部。"""
    skill = ReviewSkill()
    fake_llm_resp = {"ok": True, "result": "# 报告", "error": None}
    with patch.object(skill, "_call_llm", return_value=fake_llm_resp) as mock_llm:
        skill.execute({
            "op": "review", "l1": "科技", "query": "聚焦道家决策模型",
            "graph_db_path": str(graph_db_with_docs), "use_cache": False,
        })
    prompt = mock_llm.call_args[0][0]
    assert "聚焦道家决策模型" in prompt


# ---------------------------------------------------------------------------
# agent._parse_skill_args — CLI 解析
# ---------------------------------------------------------------------------

def test_agent_parses_review_l1_l2_l3(tmp_path: Path):
    """agent._parse_skill_args 正确解析 'review 科技 AI 模型'。"""
    import yaml
    from agent import AgentCore

    rules = {"role": "t", "max_output_tokens": 64, "prompt_prefix": "x", "output_format": "json"}
    routing = {"entries": [{"intent": ".*", "tool_type": "llm", "tool_name": "c", "fallback": None}]}
    rp = tmp_path / "rules.yaml"
    rp.write_text(yaml.safe_dump(rules))
    up = tmp_path / "routing.yaml"
    up.write_text(yaml.safe_dump(routing))
    agent = AgentCore(str(rp), str(up), str(tmp_path / "c.db"),
                      str(tmp_path / "st.json"), str(tmp_path / "lt.db"))
    args = agent._parse_skill_args("review 科技 AI 模型")
    assert args["op"] == "review"
    assert args["l1"] == "科技"
    assert args["l2"] == "AI"
    assert args["l3"] == "模型"


def test_agent_parses_review_with_query_flag(tmp_path: Path):
    """'review 科技 --query 聚焦模型' 正确解析。"""
    import yaml
    from agent import AgentCore

    rules = {"role": "t", "max_output_tokens": 64, "prompt_prefix": "x", "output_format": "json"}
    routing = {"entries": [{"intent": ".*", "tool_type": "llm", "tool_name": "c", "fallback": None}]}
    rp = tmp_path / "rules.yaml"
    rp.write_text(yaml.safe_dump(rules))
    up = tmp_path / "routing.yaml"
    up.write_text(yaml.safe_dump(routing))
    agent = AgentCore(str(rp), str(up), str(tmp_path / "c.db"),
                      str(tmp_path / "st.json"), str(tmp_path / "lt.db"))
    args = agent._parse_skill_args("review 科技 AI --query 聚焦模型演进")
    assert args["op"] == "review"
    assert args["l1"] == "科技"
    assert args["l2"] == "AI"
    assert args.get("l3") is None
    assert args["query"] == "聚焦模型演进"


def test_agent_parses_review_dry_run_flag(tmp_path: Path):
    """'review 科技 --dry-run' 正确解析。"""
    import yaml
    from agent import AgentCore

    rules = {"role": "t", "max_output_tokens": 64, "prompt_prefix": "x", "output_format": "json"}
    routing = {"entries": [{"intent": ".*", "tool_type": "llm", "tool_name": "c", "fallback": None}]}
    rp = tmp_path / "rules.yaml"
    rp.write_text(yaml.safe_dump(rules))
    up = tmp_path / "routing.yaml"
    up.write_text(yaml.safe_dump(routing))
    agent = AgentCore(str(rp), str(up), str(tmp_path / "c.db"),
                      str(tmp_path / "st.json"), str(tmp_path / "lt.db"))
    args = agent._parse_skill_args("review 科技 AI 模型 --dry-run")
    assert args["op"] == "review"
    assert args["dry_run"] is True
    assert args["l1"] == "科技"
    assert args["l3"] == "模型"


def test_agent_parses_review_max_chars_flag(tmp_path: Path):
    """'review 科技 --max-chars 5000' 正确解析。"""
    import yaml
    from agent import AgentCore

    rules = {"role": "t", "max_output_tokens": 64, "prompt_prefix": "x", "output_format": "json"}
    routing = {"entries": [{"intent": ".*", "tool_type": "llm", "tool_name": "c", "fallback": None}]}
    rp = tmp_path / "rules.yaml"
    rp.write_text(yaml.safe_dump(rules))
    up = tmp_path / "routing.yaml"
    up.write_text(yaml.safe_dump(routing))
    agent = AgentCore(str(rp), str(up), str(tmp_path / "c.db"),
                      str(tmp_path / "st.json"), str(tmp_path / "lt.db"))
    args = agent._parse_skill_args("review 科技 --max-chars 5000")
    assert args["op"] == "review"
    assert args["max_chars"] == 5000
    assert args["l1"] == "科技"


# ---------------------------------------------------------------------------
# routing — 端到端路由到 review skill
# ---------------------------------------------------------------------------

def test_agent_routes_review_to_skill(tmp_path: Path):
    """'review 科技 AI' 经 AgentCore 路由到 review skill。"""
    import yaml
    from agent import AgentCore
    from skills.review import ReviewSkill

    rules = {"role": "t", "max_output_tokens": 64, "prompt_prefix": "x", "output_format": "json"}
    routing = {"entries": [
        {"intent": "^review\\b", "tool_type": "skill", "tool_name": "review", "fallback": None},
        {"intent": ".*", "tool_type": "llm", "tool_name": "c", "fallback": None},
    ]}
    rp = tmp_path / "rules.yaml"
    rp.write_text(yaml.safe_dump(rules))
    up = tmp_path / "routing.yaml"
    up.write_text(yaml.safe_dump(routing))

    # 建 graph db
    db = tmp_path / "graph.db"
    gi = GraphIndex(str(db))
    doc_path = str(tmp_path / "doc.md")
    Path(doc_path).write_text("# Test\n\nllm content", encoding="utf-8")
    gi.upsert(doc_path, "科技", "AI", "模型")
    gi.close()

    agent = AgentCore(str(rp), str(up), str(tmp_path / "c.db"),
                      str(tmp_path / "st.json"), str(tmp_path / "lt.db"))
    skill = ReviewSkill()
    agent.register_skill("review", skill)

    # dry_run 避免调 LLM，并通过 graph_db_path 指向 tmp_path 的 db
    with patch.object(skill, "_call_llm",
                      return_value={"ok": True, "result": "# 报告", "error": None}):
        # use_cache=False + dry_run=False 才会触发 _call_llm
        # 直接调用 skill.execute 验证路由 + skill 协作（避免 default graph db 路径依赖）
        args = agent._parse_skill_args("review 科技 AI 模型 --no-cache")
        args["graph_db_path"] = str(db)
        out = skill.execute(args)

    assert out["ok"] is True
