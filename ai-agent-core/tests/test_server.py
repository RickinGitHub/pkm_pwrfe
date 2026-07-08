"""Tests for server.py FastAPI HTTP API.

Uses fastapi.testclient.TestClient. AgentCore is mocked to avoid
bootstrapping the real agent (which needs ANTHROPIC_API_KEY + sqlite).
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Set env vars so server.py module can be imported without side effects."""
    monkeypatch.setenv("RULES_CONFIG", str(tmp_path / "rules.yaml"))
    monkeypatch.setenv("ROUTING_CONFIG", str(tmp_path / "routing.yaml"))
    monkeypatch.setenv("CACHE_PATH", str(tmp_path / "cache.db"))
    monkeypatch.setenv("SHORT_TERM_PATH", str(tmp_path / "st.json"))
    monkeypatch.setenv("LONG_TERM_DB_PATH", str(tmp_path / "lt.db"))
    monkeypatch.setenv("FTS_INDEX_PATH", str(tmp_path / "fts.db"))
    monkeypatch.setenv("URL_REGISTRY_PATH", str(tmp_path / "url_map.db"))
    monkeypatch.setenv("GRAPH_DB_PATH", str(tmp_path / "graph.db"))
    monkeypatch.setenv("EMBEDDING_MODEL", "pseudo")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    (tmp_path / "rules.yaml").write_text(
        "role: test\nmax_output_tokens: 64\nprompt_prefix: be brief\noutput_format: json\n"
    )
    (tmp_path / "routing.yaml").write_text(
        "entries:\n  - intent: '.*'\n    tool_type: llm\n    tool_name: claude\n    fallback: null\n"
    )
    (tmp_path / "rag" / "corpus").mkdir(parents=True)
    (tmp_path / "rag" / "corpus" / ".gitkeep").write_text("")
    (tmp_path / "memories").mkdir()
    yield tmp_path


def _reset_server_module():
    """Clear module-level singletons so each test starts fresh."""
    import server
    server._app = None
    server._agent = None


def test_health_endpoint(_env, monkeypatch):
    _reset_server_module()

    fake_agent = MagicMock()
    fake_agent.handle = MagicMock(return_value={"ok": True, "result": "ok"})
    monkeypatch.setattr("harness.factory.build_agent", lambda: fake_agent)

    from fastapi.testclient import TestClient
    from server import _get_app
    client = TestClient(_get_app())

    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_query_endpoint(_env, monkeypatch):
    _reset_server_module()

    fake_agent = MagicMock()
    fake_agent.handle = MagicMock(return_value={"ok": True, "result": 42})
    monkeypatch.setattr("harness.factory.build_agent", lambda: fake_agent)

    from fastapi.testclient import TestClient
    from server import _get_app
    client = TestClient(_get_app())

    r = client.post("/query", json={"query": "calc 6*7"})
    assert r.status_code == 200, f"status={r.status_code} body={r.text}"
    body = r.json()
    assert body == {"ok": True, "result": 42}
    fake_agent.handle.assert_called_once_with("calc 6*7")


def test_query_serialized_under_lock(_env, monkeypatch):
    """Two concurrent /query calls must not overlap — _lock serializes them."""
    _reset_server_module()

    call_log: list[tuple[str, float]] = []
    lock_holder: dict[str, bool] = {"inside": False}

    def slow_handle(query: str):
        if lock_holder["inside"]:
            call_log.append(("overlap", time.time()))
            raise RuntimeError("overlapping handle() call detected")
        lock_holder["inside"] = True
        call_log.append(("start", time.time()))
        time.sleep(0.05)
        call_log.append(("end", time.time()))
        lock_holder["inside"] = False
        return {"ok": True, "result": query}

    fake_agent = MagicMock()
    fake_agent.handle = slow_handle
    monkeypatch.setattr("harness.factory.build_agent", lambda: fake_agent)

    from fastapi.testclient import TestClient
    from server import _get_app
    client = TestClient(_get_app())

    threads: list = []
    results: list = []

    def call():
        r = client.post("/query", json={"query": "x"})
        results.append(r.json())

    for _ in range(3):
        t = threading.Thread(target=call)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()

    assert all(r == {"ok": True, "result": "x"} for r in results)
    assert not any(tag == "overlap" for tag, _ in call_log)


def test_unknown_route_returns_404(_env, monkeypatch):
    _reset_server_module()

    fake_agent = MagicMock()
    monkeypatch.setattr("harness.factory.build_agent", lambda: fake_agent)

    from fastapi.testclient import TestClient
    from server import _get_app
    client = TestClient(_get_app())

    r = client.get("/nonexistent")
    assert r.status_code == 404


def test_missing_query_field_returns_422(_env, monkeypatch):
    _reset_server_module()

    fake_agent = MagicMock()
    monkeypatch.setattr("harness.factory.build_agent", lambda: fake_agent)

    from fastapi.testclient import TestClient
    from server import _get_app
    client = TestClient(_get_app())

    r = client.post("/query", json={})
    assert r.status_code == 422
