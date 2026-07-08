# -*- coding: utf-8 -*-
"""P0-1: _call_llm injects short_term.recent(10) as multi-turn conversation history."""
import yaml
from pathlib import Path
from unittest.mock import patch, MagicMock

from agent import AgentCore


_RULES = {
    "role": "test",
    "max_output_tokens": 128,
    "prompt_prefix": "be brief",
    "output_format": "json",
}

_ROUTING = {
    "entries": [
        {"intent": ".*", "tool_type": "llm", "tool_name": "claude", "fallback": None},
    ]
}


def _setup(tmp_path: Path):
    rp = tmp_path / "rules.yaml"
    rp.write_text(yaml.safe_dump(_RULES))
    up = tmp_path / "routing.yaml"
    up.write_text(yaml.safe_dump(_ROUTING))
    return str(rp), str(up)


def _make_agent(tmp_path: Path):
    rp, up = _setup(tmp_path)
    return AgentCore(
        rules_path=rp,
        routing_path=up,
        cache_path=str(tmp_path / "c.db"),
        short_term_path=str(tmp_path / "st.json"),
        long_term_path=str(tmp_path / "lt.db"),
    )


def test_build_llm_messages_includes_history(tmp_path):
    agent = _make_agent(tmp_path)
    agent._short.append("user", "what is 2+2")
    agent._short.append("assistant", "4")
    msgs = agent._build_llm_messages("and 3+3?", agent._rules)
    roles = [m["role"] for m in msgs]
    contents = [m["content"] for m in msgs]
    assert roles == ["user", "assistant", "user"]
    assert "what is 2+2" in contents[0]
    assert "4" in contents[1]
    assert "and 3+3?" in contents[-1]
    assert agent._rules.prompt_prefix in contents[-1]


def test_build_llm_messages_rewrites_current_query_with_prefix(tmp_path):
    """handle() appends current query before _route calls _call_llm.
    The final user message must include the prompt prefix + JSON directive."""
    agent = _make_agent(tmp_path)
    agent._short.append("user", "hello")
    # Simulate handle() having appended the current user query
    agent._short.append("user", "calc 1+1")
    msgs = agent._build_llm_messages("calc 1+1", agent._rules)
    assert msgs[-1]["role"] == "user"
    assert msgs[-1]["content"] != "calc 1+1"  # rewritten with prefix
    assert "Output JSON only" in msgs[-1]["content"]
    assert agent._rules.prompt_prefix in msgs[-1]["content"]


def test_build_llm_messages_dedupes_when_query_not_in_history(tmp_path):
    agent = _make_agent(tmp_path)
    agent._short.append("user", "previous question")
    agent._short.append("assistant", "previous answer")
    msgs = agent._build_llm_messages("brand new query", agent._rules)
    assert msgs[-1]["role"] == "user"
    assert "brand new query" in msgs[-1]["content"]


def test_call_llm_sends_multi_turn_messages(tmp_path, monkeypatch):
    """Verify the actual client.messages.create call receives multi-turn messages."""
    agent = _make_agent(tmp_path)
    agent._short.append("user", "first")
    agent._short.append("assistant", "ok")
    agent._short.append("user", "second")

    captured = {}

    class FakeBlock:
        text = '{"answer": "yes"}'

    class FakeResp:
        content = [FakeBlock()]

    def fake_create(**kwargs):
        captured["messages"] = kwargs.get("messages")
        return FakeResp()

    fake_client = MagicMock()
    fake_client.messages.create.side_effect = fake_create
    monkeypatch.setattr(agent, "_short", agent._short)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    with patch("anthropic.Anthropic", return_value=fake_client):
        out = agent._call_llm("second", agent._rules)

    assert out["ok"] is True
    assert len(captured["messages"]) >= 3  # history + current
    assert captured["messages"][-1]["role"] == "user"
    assert "Output JSON only" in captured["messages"][-1]["content"]
