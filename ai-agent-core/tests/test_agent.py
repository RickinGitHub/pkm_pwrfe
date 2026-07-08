import os
from pathlib import Path

import yaml

from agent import AgentCore
from skills.math_logic import MathLogic


_RULES = {
    "role": "test",
    "max_output_tokens": 256,
    "prompt_prefix": "be brief",
    "output_format": "json",
}

_ROUTING = {
    "entries": [
        {"intent": "^calc.*", "tool_type": "skill", "tool_name": "math", "fallback": "llm"},
        {"intent": ".*", "tool_type": "llm", "tool_name": "claude", "fallback": None},
    ]
}


def _setup(tmp_path: Path):
    rp = tmp_path / "rules.yaml"
    rp.write_text(yaml.safe_dump(_RULES))
    up = tmp_path / "routing.yaml"
    up.write_text(yaml.safe_dump(_ROUTING))
    return str(rp), str(up)


def test_skill_match_returns_result(tmp_path):
    rp, up = _setup(tmp_path)
    agent = AgentCore(
        rules_path=rp,
        routing_path=up,
        cache_path=str(tmp_path / "c.db"),
        short_term_path=str(tmp_path / "st.json"),
        long_term_path=str(tmp_path / "lt.db"),
    )
    agent.register_skill("math", MathLogic())
    out = agent.handle("calc 2 + 3 * 4")
    assert out["ok"] is True
    assert out["result"] == 14


def test_cache_hit_skips_skill(tmp_path):
    rp, up = _setup(tmp_path)
    agent = AgentCore(
        rules_path=rp,
        routing_path=up,
        cache_path=str(tmp_path / "c.db"),
        short_term_path=str(tmp_path / "st.json"),
        long_term_path=str(tmp_path / "lt.db"),
    )
    agent.register_skill("math", MathLogic())
    first = agent.handle("calc 6 * 7")
    assert first["ok"] is True and first["result"] == 42

    class _Spy:
        def __init__(self): self.calls = 0
        def execute(self, args):
            self.calls += 1
            return {"ok": True, "result": 999, "error": None}

    spy = _Spy()
    agent.register_skill("math", spy)
    second = agent.handle("calc 6 * 7")
    assert second["result"] == 42
    assert spy.calls == 0


def test_fallback_to_llm_when_skill_fails(tmp_path, monkeypatch):
    rp, up = _setup(tmp_path)
    agent = AgentCore(
        rules_path=rp,
        routing_path=up,
        cache_path=str(tmp_path / "c.db"),
        short_term_path=str(tmp_path / "st.json"),
        long_term_path=str(tmp_path / "lt.db"),
    )

    class _BadMath:
        def execute(self, args):
            return {"ok": False, "result": None, "error": "boom"}

    agent.register_skill("math", _BadMath())

    def _fake_llm(self, query, _rules):
        return {"ok": True, "result": {"llm": "answer"}, "error": None}

    monkeypatch.setattr(AgentCore, "_call_llm", _fake_llm)
    out = agent.handle("calc 1/0")
    assert out["ok"] is True
    assert out["result"] == {"llm": "answer"}


def test_short_term_records_user_and_assistant(tmp_path):
    rp, up = _setup(tmp_path)
    agent = AgentCore(
        rules_path=rp,
        routing_path=up,
        cache_path=str(tmp_path / "c.db"),
        short_term_path=str(tmp_path / "st.json"),
        long_term_path=str(tmp_path / "lt.db"),
    )
    agent.register_skill("math", MathLogic())
    agent.handle("calc 5 + 5")
    from memories.short_term import ShortTerm
    mem = ShortTerm(str(tmp_path / "st.json"))
    roles = [m["role"] for m in mem.recent(10)]
    assert "user" in roles
    assert "assistant" in roles


def test_long_term_records_triplet_on_success(tmp_path):
    rp, up = _setup(tmp_path)
    agent = AgentCore(
        rules_path=rp,
        routing_path=up,
        cache_path=str(tmp_path / "c.db"),
        short_term_path=str(tmp_path / "st.json"),
        long_term_path=str(tmp_path / "lt.db"),
    )
    agent.register_skill("math", MathLogic())
    agent.handle("calc 9 * 9")
    from memories.long_term import LongTerm
    db = LongTerm(str(tmp_path / "lt.db"))
    rows = db.query(subject="user")
    assert any("calc 9 * 9" in r[2] for r in rows)
