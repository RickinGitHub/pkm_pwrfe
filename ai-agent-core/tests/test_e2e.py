from pathlib import Path
import yaml

from agent import AgentCore
from skills.math_logic import MathLogic
from skills.file_ops import FileOps
from mcp.servers.knowledge_server import KnowledgeServer


_RULES = {
    "role": "test",
    "max_output_tokens": 256,
    "prompt_prefix": "be brief, output json",
    "output_format": "json",
}

_ROUTING = {
    "entries": [
        {"intent": "^calc.*", "tool_type": "skill", "tool_name": "math_logic", "fallback": "llm"},
        {"intent": "^(read|load|show|clean|sanitize).*file", "tool_type": "skill", "tool_name": "file_ops", "fallback": "llm"},
        {"intent": "^(lookup|search|find).*", "tool_type": "mcp", "tool_name": "knowledge", "fallback": "llm"},
        {"intent": ".*", "tool_type": "llm", "tool_name": "claude", "fallback": None},
    ]
}


def _agent(tmp_path: Path) -> AgentCore:
    rp = tmp_path / "rules.yaml"
    rp.write_text(yaml.safe_dump(_RULES))
    up = tmp_path / "routing.yaml"
    up.write_text(yaml.safe_dump(_ROUTING))
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "kb.txt").write_text("Python is a programming language used for AI.")
    agent = AgentCore(
        rules_path=str(rp),
        routing_path=str(up),
        cache_path=str(tmp_path / "c.db"),
        short_term_path=str(tmp_path / "st.json"),
        long_term_path=str(tmp_path / "lt.db"),
    )
    agent.register_skill("math_logic", MathLogic())
    agent.register_skill("file_ops", FileOps())
    agent.register_mcp("knowledge", KnowledgeServer(str(corpus)))
    return agent


def test_e2e_math_skill_returns_correct_answer(tmp_path):
    agent = _agent(tmp_path)
    out = agent.handle("calc 7 * 6")
    assert out["ok"] is True
    assert out["result"] == 42


def test_e2e_second_call_served_from_cache(tmp_path):
    agent = _agent(tmp_path)
    out1 = agent.handle("calc 8 * 8")
    out2 = agent.handle("calc 8 * 8")
    assert out1 == out2
    assert out1["result"] == 64


def test_e2e_file_ops_skill(tmp_path):
    f = tmp_path / "data.txt"
    f.write_text("hello\n\nworld\n")
    agent = _agent(tmp_path)
    out = agent.handle(f"clean file {f}")
    assert out["ok"] is True
    assert out["result"] == "hello\nworld"


def test_e2e_mcp_knowledge_lookup(tmp_path):
    agent = _agent(tmp_path)
    out = agent.handle("lookup python")
    assert out["ok"] is True
    assert "python" in out["result"].lower()


def test_e2e_memory_state_after_calls(tmp_path):
    agent = _agent(tmp_path)
    agent.handle("calc 1 + 1")
    agent.handle("calc 2 + 2")
    from memories.short_term import ShortTerm
    mem = ShortTerm(str(tmp_path / "st.json"))
    recent = mem.recent(20)
    assert len(recent) >= 4
    assert recent[-1]["role"] == "assistant"


def test_e2e_unknown_intent_routes_to_llm_with_no_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    agent = _agent(tmp_path)
    out = agent.handle("tell me a joke")
    assert out["ok"] is False
    assert "api_key" in out["error"].lower()
