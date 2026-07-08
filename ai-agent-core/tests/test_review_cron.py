"""Tests for review_cron.py daemon.

Uses env-var isolation + mocked ReviewSkill to avoid bootstrapping
the real agent or hitting sqlite/graph dependencies.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _set_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
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
    monkeypatch.setenv("REVIEW_CRON_PID_FILE", str(tmp_path / "review_cron.pid"))
    monkeypatch.setenv("REVIEW_CRON_LOG_FILE", str(tmp_path / "review_cron.log"))
    monkeypatch.setenv("REVIEWS_DIR", str(tmp_path / "reviews"))
    (tmp_path / "rules.yaml").write_text(
        "role: test\nmax_output_tokens: 64\nprompt_prefix: be brief\noutput_format: json\n"
    )
    (tmp_path / "routing.yaml").write_text(
        "entries:\n  - intent: '.*'\n    tool_type: llm\n    tool_name: claude\n    fallback: null\n"
    )
    (tmp_path / "rag" / "corpus").mkdir(parents=True)
    (tmp_path / "rag" / "corpus" / ".gitkeep").write_text("")
    (tmp_path / "memories").mkdir()


def _make_graph_db(graph_db: Path, l1s: list[str]) -> None:
    conn = sqlite3.connect(str(graph_db))
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS document_graph (
                path TEXT, l1 TEXT, l2 TEXT, l3 TEXT, l4 TEXT, l5 TEXT,
                chunk_count INTEGER, sha TEXT, updated_at REAL
            )
        """)
        for l1 in l1s:
            conn.execute(
                "INSERT INTO document_graph (path, l1) VALUES (?, ?)",
                (f"doc/{l1}.md", l1),
            )
        conn.commit()
    finally:
        conn.close()


def test_next_run_returns_future_timestamp():
    import review_cron
    now = 1_700_000_000.0
    ts = review_cron._next_run(every_hours=24, now=now)
    assert ts == now + 24 * 3600.0
    assert ts > now


def test_next_run_zero_returns_now():
    import review_cron
    now = 1_700_000_000.0
    ts = review_cron._next_run(every_hours=0, now=now)
    assert ts == now


def test_list_distinct_l1(tmp_path: Path):
    import review_cron
    graph_db = tmp_path / "graph.db"
    _make_graph_db(graph_db, ["历史", "科技", "历史", "艺术"])
    l1s = review_cron._list_distinct_l1(graph_db)
    assert l1s == ["历史", "科技", "艺术"]


def test_list_distinct_l1_missing_db_returns_empty(tmp_path: Path, caplog):
    import review_cron
    missing = tmp_path / "nope.db"
    out = review_cron._list_distinct_l1(missing)
    assert out == []


def test_run_cycle_invokes_review_per_l1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _set_env(monkeypatch, tmp_path)
    graph_db = tmp_path / "graph.db"
    _make_graph_db(graph_db, ["历史", "科技"])

    fake_review = MagicMock()
    fake_review.execute = MagicMock(return_value={
        "ok": True,
        "result": {"report": "# report for {}\nbody".format("x")},
    })
    fake_agent = MagicMock()
    fake_agent._skills = {"review": fake_review}

    monkeypatch.setattr("harness.factory.build_agent", lambda: fake_agent)

    reviews_dir = tmp_path / "reviews"
    import review_cron
    written = review_cron._run_cycle(reviews_dir, graph_db)

    assert written == 2
    assert fake_review.execute.call_count == 2
    called_l1s = [call.args[0]["l1"] for call in fake_review.execute.call_args_list]
    assert set(called_l1s) == {"历史", "科技"}
    reports = sorted(reviews_dir.glob("*.md"))
    assert len(reports) == 2
    for r in reports:
        assert r.stat().st_size > 0


def test_run_cycle_handles_review_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _set_env(monkeypatch, tmp_path)
    graph_db = tmp_path / "graph.db"
    _make_graph_db(graph_db, ["broken"])

    fake_review = MagicMock()
    fake_review.execute = MagicMock(return_value={"ok": False, "error": "boom"})
    fake_agent = MagicMock()
    fake_agent._skills = {"review": fake_review}
    monkeypatch.setattr("harness.factory.build_agent", lambda: fake_agent)

    import review_cron
    written = review_cron._run_cycle(tmp_path / "reviews", graph_db)
    assert written == 0
    failed_report = (tmp_path / "reviews").glob("*.md").__next__()
    assert "FAILED" in failed_report.read_text(encoding="utf-8")


def test_run_cycle_no_l1_returns_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _set_env(monkeypatch, tmp_path)
    graph_db = tmp_path / "graph.db"
    _make_graph_db(graph_db, [])

    import review_cron
    written = review_cron._run_cycle(tmp_path / "reviews", graph_db)
    assert written == 0


def test_run_forever_stops_on_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """stop_event.set() must cause run_forever to exit within poll_seconds*2."""
    _set_env(monkeypatch, tmp_path)
    import review_cron

    monkeypatch.setattr(review_cron, "_run_cycle", lambda *a, **kw: 0)

    stop_event = threading.Event()

    def trigger_stop():
        time.sleep(0.2)
        stop_event.set()

    threading.Thread(target=trigger_stop, daemon=True).start()

    start = time.time()
    rc = review_cron.run_forever(every_hours=999, poll_seconds=1, stop_event=stop_event)
    elapsed = time.time() - start

    assert rc == 0
    assert elapsed < 3.0


def test_run_forever_runs_cycle_when_due(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """every_hours=0 → cycle runs immediately, then reschedules."""
    _set_env(monkeypatch, tmp_path)
    import review_cron

    cycle_calls: list = []
    monkeypatch.setattr(review_cron, "_run_cycle", lambda *a, **kw: cycle_calls.append(time.time()) or 1)

    stop_event = threading.Event()

    def trigger_stop():
        time.sleep(0.5)
        stop_event.set()

    threading.Thread(target=trigger_stop, daemon=True).start()

    rc = review_cron.run_forever(every_hours=0, poll_seconds=1, stop_event=stop_event)
    assert rc == 0
    assert len(cycle_calls) >= 1


@pytest.mark.integration
def test_lifecycle_start_status_stop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """start → status(running) → stop → status(not running).

    Uses every_hours=999 + poll=1 to avoid actually running a cycle during the test.
    """
    _set_env(monkeypatch, tmp_path)
    import review_cron

    monkeypatch.setattr(review_cron, "_run_cycle", lambda *a, **kw: 0)

    rc = review_cron.cmd_start(every_hours=999, poll_seconds=1)
    if rc != 0:
        pytest.skip("background start not supported in this env")
    try:
        time.sleep(0.5)
        pid = review_cron._read_pid()
        assert pid is not None
        assert review_cron._is_running(pid)
    finally:
        review_cron.cmd_stop(None)
    time.sleep(0.3)
    pid = review_cron._read_pid()
    assert pid is None
