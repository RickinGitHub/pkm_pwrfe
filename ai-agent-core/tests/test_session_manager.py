"""Phase 1 tests — M6 SessionManager + SessionState."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from harness.bot.session_manager import SessionManager, SessionState


@pytest.fixture
def mgr(tmp_path: Path) -> SessionManager:
    return SessionManager(base_dir=str(tmp_path / "sessions"), ttl_minutes=30, max_sessions=3)


class TestSessionState:
    def test_new_state_is_idle(self):
        s = SessionState(chat_id=1)
        assert s.is_idle()
        assert s.pending_action is None

    def test_set_pending_marks_dirty(self):
        s = SessionState(chat_id=1)
        s.set_pending("await_ingest", {"filepath": "x.md"})
        assert not s.is_idle()
        assert s.pending_action == "await_ingest"
        assert s.pending_data == {"filepath": "x.md"}
        assert s._dirty

    def test_clear_pending_returns_to_idle(self):
        s = SessionState(chat_id=1)
        s.set_pending("await_ingest", {"f": "x"})
        s.clear_pending()
        assert s.is_idle()
        assert s._dirty

    def test_to_dict_excludes_dirty(self):
        s = SessionState(chat_id=1)
        d = s.to_dict()
        assert "_dirty" not in d
        assert d["chat_id"] == 1

    def test_from_dict_ignores_unknown_fields(self):
        d = {
            "chat_id": 5,
            "pending_action": "x",
            "future_field_not_known": "ignored",
        }
        s = SessionState.from_dict(d)
        assert s.chat_id == 5
        assert s.pending_action == "x"


class TestSessionManagerLifecycle:
    def test_get_or_create_new(self, mgr: SessionManager):
        s = mgr.get_or_create(1)
        assert s.chat_id == 1
        assert s.is_idle()

    def test_get_or_create_returns_same_instance(self, mgr: SessionManager):
        a = mgr.get_or_create(1)
        b = mgr.get_or_create(1)
        assert a is b

    def test_get_returns_none_for_unknown(self, mgr: SessionManager):
        assert mgr.get(999) is None

    def test_save_persists_to_file(self, mgr: SessionManager, tmp_path: Path):
        s = mgr.get_or_create(42)
        s.set_pending("await_ingest", {"filepath": "a.md"})
        mgr.save(42)
        path = tmp_path / "sessions" / "42" / "session.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["pending_action"] == "await_ingest"
        assert data["pending_data"] == {"filepath": "a.md"}

    def test_save_clears_dirty_flag(self, mgr: SessionManager):
        s = mgr.get_or_create(1)
        s.set_pending("x", {})
        mgr.save(1)
        assert not s._dirty
        # Second save is a no-op
        mgr.save(1)

    def test_reload_from_file(self, mgr: SessionManager):
        s = mgr.get_or_create(7)
        s.set_pending("await_ingest", {"filepath": "x"})
        mgr.save(7)
        # Simulate restart
        mgr._hot.clear()
        s2 = mgr.get(7)
        assert s2 is not None
        assert s2.pending_action == "await_ingest"
        assert s2.pending_data == {"filepath": "x"}

    def test_clear_removes_file_and_hot(self, mgr: SessionManager, tmp_path: Path):
        s = mgr.get_or_create(1)
        s.set_pending("x", {})
        mgr.save(1)
        path = tmp_path / "sessions" / "1" / "session.json"
        assert path.exists()
        mgr.clear(1)
        assert not path.exists()
        assert 1 not in mgr._hot

    def test_corrupted_file_returns_none(self, mgr: SessionManager, tmp_path: Path):
        path = tmp_path / "sessions" / "1" / "session.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not valid json", encoding="utf-8")
        assert mgr.get(1) is None

    def test_atomic_write_no_partial_file(self, mgr: SessionManager, tmp_path: Path):
        s = mgr.get_or_create(1)
        s.set_pending("x", {})
        mgr.save(1)
        # No .tmp file should remain after save
        tmp = tmp_path / "sessions" / "1" / "session.json.tmp"
        assert not tmp.exists()


class TestEviction:
    def test_evict_expired_drops_from_hot(self, tmp_path: Path):
        mgr = SessionManager(base_dir=str(tmp_path / "s"), ttl_minutes=0, max_sessions=1)
        s1 = mgr.get_or_create(1)
        # Force updated_at into the past
        s1.updated_at = time.time() - 3600
        s1._dirty = False
        # New chat triggers eviction (max_sessions=1)
        mgr.get_or_create(2)
        assert 1 not in mgr._hot

    def test_evict_expired_saves_dirty_state(self, tmp_path: Path):
        mgr = SessionManager(base_dir=str(tmp_path / "s"), ttl_minutes=0, max_sessions=1)
        s1 = mgr.get_or_create(1)
        s1.updated_at = time.time() - 3600
        s1.set_pending("await", {})
        # Trigger eviction
        mgr.get_or_create(2)
        # Dirty state should have been persisted before eviction
        path = tmp_path / "s" / "1" / "session.json"
        assert path.exists()
