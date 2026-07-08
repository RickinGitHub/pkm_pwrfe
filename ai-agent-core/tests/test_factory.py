"""Phase 1 tests: harness.factory.build_agent() factory.

Verifies the factory wires up all expected skills + MCP servers, and that
repeated calls don't raise (bootstrap_memory idempotency).
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest


def test_build_agent_registers_all_expected_skills(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    for name, val in {
        "RULES_CONFIG": str(tmp_path / "rules.yaml"),
        "ROUTING_CONFIG": str(tmp_path / "routing.yaml"),
        "CACHE_PATH": str(tmp_path / "cache.db"),
        "SHORT_TERM_PATH": str(tmp_path / "st.json"),
        "LONG_TERM_DB_PATH": str(tmp_path / "lt.db"),
        "FTS_INDEX_PATH": str(tmp_path / "fts.db"),
        "URL_REGISTRY_PATH": str(tmp_path / "url_map.db"),
        "EMBEDDING_MODEL": "pseudo",
        "ANTHROPIC_API_KEY": "test-key-not-real",
    }.items():
        monkeypatch.setenv(name, val)

    (tmp_path / "rules.yaml").write_text(
        "role: test\nmax_output_tokens: 64\nprompt_prefix: be brief\noutput_format: json\n"
    )
    (tmp_path / "routing.yaml").write_text(
        "entries:\n  - intent: '.*'\n    tool_type: llm\n    tool_name: claude\n    fallback: null\n"
    )
    (tmp_path / "rag" / "corpus").mkdir(parents=True)
    (tmp_path / "rag" / "corpus" / ".gitkeep").write_text("")
    (tmp_path / "memories").mkdir()

    with patch("harness.factory.build_agent.__wrapped__", None) if False else patch.dict(
        os.environ, {"GRAPH_DB_PATH": str(tmp_path / "graph.db")}
    ):
        from harness.factory import build_agent
        agent = build_agent()

    expected_skills = {
        "math_logic", "file_ops", "fetch_web", "context", "reflect",
        "review", "find_ops", "grep_ops", "tree_ops", "pipeline_ops", "react",
    }
    missing = expected_skills - set(agent._skills.keys())
    assert not missing, f"missing skills: {missing}"
    assert "react" in agent._skills
    assert "knowledge" in agent._mcp._tools
    assert "hybrid_knowledge" in agent._mcp._tools
    assert "file_search" in agent._mcp._tools


def test_build_agent_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Second build_agent() call must not raise even if memory files exist."""
    monkeypatch.chdir(tmp_path)
    for name, val in {
        "RULES_CONFIG": str(tmp_path / "rules.yaml"),
        "ROUTING_CONFIG": str(tmp_path / "routing.yaml"),
        "CACHE_PATH": str(tmp_path / "cache.db"),
        "SHORT_TERM_PATH": str(tmp_path / "st.json"),
        "LONG_TERM_DB_PATH": str(tmp_path / "lt.db"),
        "FTS_INDEX_PATH": str(tmp_path / "fts.db"),
        "URL_REGISTRY_PATH": str(tmp_path / "url_map.db"),
        "EMBEDDING_MODEL": "pseudo",
        "ANTHROPIC_API_KEY": "test-key-not-real",
        "GRAPH_DB_PATH": str(tmp_path / "graph.db"),
    }.items():
        monkeypatch.setenv(name, val)

    (tmp_path / "rules.yaml").write_text(
        "role: test\nmax_output_tokens: 64\nprompt_prefix: be brief\noutput_format: json\n"
    )
    (tmp_path / "routing.yaml").write_text(
        "entries:\n  - intent: '.*'\n    tool_type: llm\n    tool_name: claude\n    fallback: null\n"
    )
    (tmp_path / "rag" / "corpus").mkdir(parents=True)
    (tmp_path / "rag" / "corpus" / ".gitkeep").write_text("")
    (tmp_path / "memories").mkdir()

    from harness.factory import build_agent
    a1 = build_agent()
    a2 = build_agent()
    assert "react" in a2._skills
    assert "react" in a1._skills
