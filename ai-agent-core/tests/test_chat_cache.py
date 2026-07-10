"""Phase 1 tests — M7 ChatCache (memory hot + JSONL cold)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.bot.chat_cache import ChatCache


@pytest.fixture
def cache(tmp_path: Path) -> ChatCache:
    return ChatCache(base_dir=str(tmp_path / "sessions"), hot_size=3, ttl_minutes=30)


class TestAppendAndGetContext:
    def test_append_then_get_from_hot(self, cache: ChatCache):
        cache.append(1, "user", "hi")
        cache.append(1, "assistant", "hello")
        ctx = cache.get_context(1, limit=10)
        assert len(ctx) == 2
        assert ctx[0]["content"] == "hi"
        assert ctx[1]["role"] == "assistant"

    def test_hot_size_evicts_oldest(self, cache: ChatCache):
        for i in range(5):
            cache.append(1, "user", f"m{i}")
        ctx = cache.get_context(1, limit=10)
        assert len(ctx) == 3  # hot_size=3
        assert ctx[0]["content"] == "m2"
        assert ctx[-1]["content"] == "m4"

    def test_file_persists_after_append(self, cache: ChatCache, tmp_path: Path):
        cache.append(42, "user", "on disk")
        path = tmp_path / "sessions" / "42" / "chat.jsonl"
        assert path.exists()
        line = path.read_text(encoding="utf-8").strip()
        entry = json.loads(line)
        assert entry["content"] == "on disk"
        assert entry["role"] == "user"

    def test_read_tail_on_cache_miss(self, cache: ChatCache):
        cache.append(1, "user", "a")
        cache.append(1, "user", "b")
        # Simulate restart by clearing hot cache
        cache._hot.clear()
        ctx = cache.get_context(1, limit=10)
        assert len(ctx) == 2
        assert ctx[0]["content"] == "a"
        assert ctx[1]["content"] == "b"

    def test_limit_truncates_context(self, tmp_path: Path):
        cache = ChatCache(base_dir=str(tmp_path / "sessions"), hot_size=20, ttl_minutes=30)
        for i in range(10):
            cache.append(1, "user", f"m{i}")
        ctx = cache.get_context(1, limit=4)
        assert len(ctx) == 4
        assert ctx[0]["content"] == "m6"


class TestClear:
    def test_clear_writes_separator(self, cache: ChatCache, tmp_path: Path):
        cache.append(1, "user", "before")
        cache.clear(1)
        path = tmp_path / "sessions" / "1" / "chat.jsonl"
        text = path.read_text(encoding="utf-8")
        assert "--- cleared at" in text

    def test_clear_empties_hot(self, cache: ChatCache):
        cache.append(1, "user", "x")
        cache.clear(1)
        assert 1 not in cache._hot

    def test_read_tail_skips_separator(self, cache: ChatCache):
        """After clear(), _read_tail returns entries from both sides of the
        separator but skips the separator line itself (design §4.2)."""
        cache.append(1, "user", "before")
        cache.clear(1)
        cache.append(1, "user", "after")
        cache._hot.clear()
        ctx = cache.get_context(1, limit=10)
        # Per design: separator is skipped, but pre-clear entries remain
        # (deque maxlen behavior). clear() is for auditability, not truncation.
        assert len(ctx) == 2
        contents = [e["content"] for e in ctx]
        assert "before" in contents
        assert "after" in contents
        # Separator itself must not appear as a context entry
        for e in ctx:
            assert not e["content"].startswith("---")


class TestIsolation:
    def test_chats_isolated(self, cache: ChatCache):
        cache.append(1, "user", "one")
        cache.append(2, "user", "two")
        assert len(cache.get_context(1)) == 1
        assert cache.get_context(1)[0]["content"] == "one"
        assert cache.get_context(2)[0]["content"] == "two"


class TestCorruptionRecovery:
    def test_bad_lines_skipped(self, cache: ChatCache, tmp_path: Path):
        path = tmp_path / "sessions" / "1" / "chat.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            '{"role":"user","content":"good"}\n'
            'this is not json\n'
            '{"role":"user","content":"also good"}\n',
            encoding="utf-8",
        )
        ctx = cache.get_context(1, limit=10)
        assert len(ctx) == 2
        assert ctx[0]["content"] == "good"

    def test_missing_file_returns_empty(self, cache: ChatCache):
        assert cache.get_context(999, limit=5) == []
