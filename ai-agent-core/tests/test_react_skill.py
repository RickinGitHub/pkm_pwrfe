"""Tests for skills/react.py ReAct tool-use loop.

Mocks the Anthropic client so no network/API key required.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class _FakeTextBlock:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class _FakeToolUseBlock:
    type = "tool_use"

    def __init__(self, id: str, name: str, inp: dict) -> None:
        self.id = id
        self.name = name
        self.input = inp


class _FakeResp:
    def __init__(self, content: list, stop_reason: str) -> None:
        self.content = content
        self.stop_reason = stop_reason


def _make_agent_with_skills(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, skills: dict | None = None):
    """Build a minimal fake agent exposing _skills + _mcp._tools."""
    agent = MagicMock()
    agent._skills = dict(skills or {})
    mcp = MagicMock()
    mcp._tools = {}
    mcp.call = MagicMock(return_value={"ok": True, "result": "mcp-result"})
    agent._mcp = mcp
    return agent


def _install_fake_client(monkeypatch: pytest.MonkeyPatch, responses: list):
    """Patch ReactSkill._get_client to return a fake client with queued responses."""
    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = MagicMock(side_effect=responses)
    monkeypatch.setattr("skills.react.ReactSkill._get_client", lambda self: client)
    return client


def _set_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-test")


def test_single_tool_use_then_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """LLM calls one tool, gets result, then ends with final answer."""
    _set_env(monkeypatch, tmp_path)

    math_skill = MagicMock()
    math_skill.execute = MagicMock(return_value={"ok": True, "result": 4})

    agent = _make_agent_with_skills(tmp_path, monkeypatch, skills={"math_logic": math_skill})

    responses = [
        _FakeResp(
            content=[_FakeToolUseBlock(id="t1", name="skill_math_logic", inp={"args": {"expr": "2+2"}})],
            stop_reason="tool_use",
        ),
        _FakeResp(
            content=[_FakeTextBlock("The answer is 4.")],
            stop_reason="end_turn",
        ),
    ]
    _install_fake_client(monkeypatch, responses)

    from skills.react import ReactSkill
    skill = ReactSkill(agent=agent)
    out = skill.execute({"query": "what is 2+2?", "max_steps": 5})

    assert out["ok"], out.get("error")
    assert out["result"]["answer"] == "The answer is 4."
    assert out["result"]["steps"] == 2
    assert len(out["result"]["tool_calls"]) == 1
    tc = out["result"]["tool_calls"][0]
    assert tc["tool"] == "skill_math_logic"
    assert tc["result"] == {"ok": True, "result": 4}
    math_skill.execute.assert_called_once_with({"expr": "2+2"})


def test_max_steps_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Hit max_steps cap without end_turn — loop must terminate gracefully."""
    _set_env(monkeypatch, tmp_path)

    math_skill = MagicMock()
    math_skill.execute = MagicMock(return_value={"ok": True, "result": 0})
    agent = _make_agent_with_skills(tmp_path, monkeypatch, skills={"math_logic": math_skill})

    tool_resp = _FakeResp(
        content=[_FakeToolUseBlock(id=f"t{i}", name="skill_math_logic", inp={"args": {}}) for i in range(2)],
        stop_reason="tool_use",
    )
    responses = [tool_resp, tool_resp]
    _install_fake_client(monkeypatch, responses)

    from skills.react import ReactSkill
    skill = ReactSkill(agent=agent)
    out = skill.execute({"query": "loop forever", "max_steps": 2})

    assert out["ok"], out.get("error")
    assert out["result"]["steps"] == 2
    assert out["result"].get("stopped_by") == "max_steps"
    assert len(out["result"]["tool_calls"]) == 4


def test_max_steps_hard_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """max_steps > 10 is clamped to 10."""
    _set_env(monkeypatch, tmp_path)
    agent = _make_agent_with_skills(tmp_path, monkeypatch, skills={
        "math_logic": MagicMock(execute=MagicMock(return_value={"ok": True, "result": 0}))
    })

    tool_resp = _FakeResp(
        content=[_FakeToolUseBlock(id="t0", name="skill_math_logic", inp={"args": {}})],
        stop_reason="tool_use",
    )
    responses = [tool_resp] * 15
    _install_fake_client(monkeypatch, responses)

    from skills.react import ReactSkill
    skill = ReactSkill(agent=agent)
    out = skill.execute({"query": "x", "max_steps": 99})

    assert out["ok"]
    assert out["result"]["steps"] == 10
    assert out["result"]["stopped_by"] == "max_steps"


def test_allowed_tools_filters_schemas(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """allowed_tools=['math_logic'] excludes other skills from tool schemas."""
    _set_env(monkeypatch, tmp_path)

    math_skill = MagicMock()
    math_skill.execute = MagicMock(return_value={"ok": True, "result": 4})
    file_skill = MagicMock()
    file_skill.execute = MagicMock(return_value={"ok": True, "result": "file"})

    agent = _make_agent_with_skills(tmp_path, monkeypatch, skills={
        "math_logic": math_skill,
        "file_ops": file_skill,
    })

    captured_tools: list = []

    def fake_create(*, model, max_tokens, tools, messages):
        captured_tools.append(tools)
        return _FakeResp(content=[_FakeTextBlock("done")], stop_reason="end_turn")

    client = MagicMock()
    client.messages.create = fake_create
    monkeypatch.setattr("skills.react.ReactSkill._get_client", lambda self: client)

    from skills.react import ReactSkill
    skill = ReactSkill(agent=agent)
    out = skill.execute({"query": "q", "allowed_tools": ["math_logic"]})

    assert out["ok"]
    tool_names = {t["name"] for t in captured_tools[0]}
    assert "skill_math_logic" in tool_names
    assert "skill_file_ops" not in tool_names


def test_missing_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Missing ANTHROPIC_API_KEY → err envelope."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    agent = _make_agent_with_skills(tmp_path, monkeypatch)

    from skills.react import ReactSkill
    skill = ReactSkill(agent=agent)
    out = skill.execute({"query": "anything"})

    assert not out["ok"]
    assert "ANTHROPIC_API_KEY" in out["error"]


def test_long_tool_result_truncated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Tool result >2000 chars is truncated in the message sent back to LLM."""
    _set_env(monkeypatch, tmp_path)

    big_result = "x" * 5000
    math_skill = MagicMock()
    math_skill.execute = MagicMock(return_value={"ok": True, "result": big_result})
    agent = _make_agent_with_skills(tmp_path, monkeypatch, skills={"math_logic": math_skill})

    captured_messages: list = []

    def fake_create(*, model, max_tokens, tools, messages):
        captured_messages.append([dict(m) for m in messages])
        if len(captured_messages) == 1:
            return _FakeResp(
                content=[_FakeToolUseBlock(id="t1", name="skill_math_logic", inp={"args": {}})],
                stop_reason="tool_use",
            )
        return _FakeResp(content=[_FakeTextBlock("done")], stop_reason="end_turn")

    client = MagicMock()
    client.messages.create = fake_create
    monkeypatch.setattr("skills.react.ReactSkill._get_client", lambda self: client)

    from skills.react import ReactSkill
    skill = ReactSkill(agent=agent)
    out = skill.execute({"query": "q", "max_steps": 3})

    assert out["ok"]
    last_msg = captured_messages[1][-1]
    assert last_msg["role"] == "user"
    content = last_msg["content"][0]
    assert content["type"] == "tool_result"
    assert "[truncated]" in content["content"]
    assert len(content["content"]) < 2030


def test_no_query_returns_err(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _set_env(monkeypatch, tmp_path)
    agent = _make_agent_with_skills(tmp_path, monkeypatch)

    from skills.react import ReactSkill
    skill = ReactSkill(agent=agent)
    out = skill.execute({})

    assert not out["ok"]
    assert "query" in out["error"]


def test_no_tools_available(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Agent has no skills and no MCP tools → err."""
    _set_env(monkeypatch, tmp_path)
    agent = _make_agent_with_skills(tmp_path, monkeypatch, skills={})
    agent._mcp._tools = {}

    from skills.react import ReactSkill
    skill = ReactSkill(agent=agent)
    out = skill.execute({"query": "anything"})

    assert not out["ok"]
    assert "no tools" in out["error"]


def test_unknown_tool_returns_error_envelope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """If LLM hallucinates a tool name, dispatch returns error dict, loop continues."""
    _set_env(monkeypatch, tmp_path)
    math_skill = MagicMock()
    agent = _make_agent_with_skills(tmp_path, monkeypatch, skills={"math_logic": math_skill})

    responses = [
        _FakeResp(
            content=[_FakeToolUseBlock(id="t1", name="skill_nonexistent", inp={"args": {}})],
            stop_reason="tool_use",
        ),
        _FakeResp(content=[_FakeTextBlock("done")], stop_reason="end_turn"),
    ]
    _install_fake_client(monkeypatch, responses)

    from skills.react import ReactSkill
    skill = ReactSkill(agent=agent)
    out = skill.execute({"query": "q", "max_steps": 3})

    assert out["ok"]
    tc = out["result"]["tool_calls"][0]
    assert "error" in tc["result"]
    assert "unknown skill" in tc["result"]["error"]
