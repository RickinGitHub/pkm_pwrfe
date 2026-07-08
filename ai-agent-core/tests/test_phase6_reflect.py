"""Phase 6 tests: ReflectSkill — practice feedback re-wires old notes.

Covers ReflectSkill.execute, _do_reflect, _is_duplicate, _resolve_path,
_CMD_RE parsing, _hash_text helper, frontmatter revisions array update,
atomic write, dedup window logic.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from skills.reflect import ReflectSkill, _CMD_RE, _hash_text, _parse_iso


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def corpus_dir(tmp_path: Path, monkeypatch) -> Path:
    """Create a fake corpus dir and set CORPUS_DIR env."""
    cd = tmp_path / "corpus"
    cd.mkdir()
    monkeypatch.setenv("CORPUS_DIR", str(cd))
    return cd


@pytest.fixture
def note_path(corpus_dir: Path) -> Path:
    """Create a test note with frontmatter."""
    note = corpus_dir / "test_note.md"
    note.write_text(
        "---\n"
        "l1: 科技\n"
        "l2: AI\n"
        "l3: 模型\n"
        "title: Test Note\n"
        "fetched_at: 2026-01-01T00:00:00\n"
        "---\n\n"
        "# Test Note\n\n"
        "Original content.\n",
        encoding="utf-8",
    )
    return note


@pytest.fixture
def skill(corpus_dir: Path) -> ReflectSkill:
    return ReflectSkill()


# ---------------------------------------------------------------------------
# 1. _do_reflect core behavior
# ---------------------------------------------------------------------------

def test_reflect_appends_practice_section(note_path: Path, skill: ReflectSkill):
    out = skill.execute({
        "raw_query": f"reflect {note_path} --insight 新洞察",
    })
    assert out["ok"] is True
    assert out["result"]["action"] == "appended"
    today = datetime.now().strftime("%Y-%m-%d")
    content = note_path.read_text(encoding="utf-8")
    assert f"## 实践复盘 {today}" in content
    assert "新洞察" in content
    assert "> insight: 新洞察" in content


def test_reflect_updates_frontmatter_revisions(note_path: Path, skill: ReflectSkill):
    out = skill.execute({
        "raw_query": f"reflect {note_path} --insight 洞察1 --source 项目A",
    })
    assert out["ok"] is True
    assert out["result"]["total_revisions"] == 1

    fm = skill._parse_frontmatter(note_path.read_text(encoding="utf-8"))
    assert isinstance(fm["revisions"], list)
    assert len(fm["revisions"]) == 1
    rev = fm["revisions"][0]
    assert rev["insight"] == "洞察1"
    assert rev["source_event"] == "项目A"
    assert "date" in rev


def test_reflect_source_event_optional(note_path: Path, skill: ReflectSkill):
    """不传 --source 时不写 source_event 字段。"""
    out = skill.execute({
        "raw_query": f"reflect {note_path} --insight 仅洞察",
    })
    assert out["ok"] is True
    fm = skill._parse_frontmatter(note_path.read_text(encoding="utf-8"))
    assert "source_event" not in fm["revisions"][0]


def test_reflect_preserves_existing_frontmatter(note_path: Path, skill: ReflectSkill):
    """已有 frontmatter 含其他字段时不丢失。"""
    out = skill.execute({
        "raw_query": f"reflect {note_path} --insight 新",
    })
    assert out["ok"] is True
    fm = skill._parse_frontmatter(note_path.read_text(encoding="utf-8"))
    # 原字段保留
    assert fm["l1"] == "科技"
    assert fm["l2"] == "AI"
    assert fm["l3"] == "模型"
    assert fm["title"] == "Test Note"
    # 新字段
    assert "revisions" in fm


# ---------------------------------------------------------------------------
# 2. Dedup logic
# ---------------------------------------------------------------------------

def test_reflect_dedup_skips_same_insight_within_24h(note_path: Path, skill: ReflectSkill):
    """相同 insight 24h 内重复调用 → skipped。"""
    skill.execute({"raw_query": f"reflect {note_path} --insight 相同洞察"})
    out2 = skill.execute({"raw_query": f"reflect {note_path} --insight 相同洞察"})
    assert out2["ok"] is True
    assert out2["result"]["action"] == "skipped"
    assert "duplicate" in out2["result"]["reason"].lower()


def test_reflect_dedup_allows_different_insight(note_path: Path, skill: ReflectSkill):
    """不同 insight 不被去重。"""
    skill.execute({"raw_query": f"reflect {note_path} --insight 洞察A"})
    out2 = skill.execute({"raw_query": f"reflect {note_path} --insight 洞察B"})
    assert out2["ok"] is True
    assert out2["result"]["action"] == "appended"
    assert out2["result"]["total_revisions"] == 2


def test_reflect_dedup_allows_after_window(note_path: Path, skill: ReflectSkill):
    """超过 dedup_hours 后允许追加相同 insight。"""
    skill.execute({"raw_query": f"reflect {note_path} --insight 循环洞察"})
    fm = skill._parse_frontmatter(note_path.read_text(encoding="utf-8"))
    old_time = (datetime.now(timezone.utc) - timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ")
    fm["revisions"][0]["date"] = old_time
    raw = note_path.read_text(encoding="utf-8")
    fm_yaml = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip()
    new_raw = f"---\n{fm_yaml}\n---\n" + raw.split("---", 2)[2].lstrip("\n")
    note_path.write_text(new_raw, encoding="utf-8")

    out2 = skill.execute({"raw_query": f"reflect {note_path} --insight 循环洞察"})
    assert out2["ok"] is True
    assert out2["result"]["action"] == "appended"


def test_reflect_dedup_window_env_override(tmp_path: Path, monkeypatch):
    """REFLECT_DEDUP_WINDOW_HOURS 环境变量可调窗口。"""
    monkeypatch.setenv("CORPUS_DIR", str(tmp_path))
    monkeypatch.setenv("REFLECT_DEDUP_WINDOW_HOURS", "1")
    note = tmp_path / "n.md"
    note.write_text("# N\n\ncontent\n", encoding="utf-8")
    skill = ReflectSkill()
    assert skill._dedup_hours == 1.0


# ---------------------------------------------------------------------------
# 3. No-insight path → await_insight
# ---------------------------------------------------------------------------

def test_reflect_no_insight_returns_await_insight(note_path: Path, skill: ReflectSkill):
    out = skill.execute({"raw_query": f"reflect {note_path}"})
    assert out["ok"] is True
    assert out["result"]["action"] == "await_insight"
    assert out["result"]["title"] == "Test Note"
    assert out["result"]["l1"] == "科技"
    assert out["result"]["revision_count"] == 0
    assert "hint" in out["result"]


# ---------------------------------------------------------------------------
# 4. Error paths
# ---------------------------------------------------------------------------

def test_reflect_missing_path_returns_error(skill: ReflectSkill):
    out = skill.execute({"raw_query": "reflect"})
    assert out["ok"] is False
    assert "path" in out["error"].lower() or "requires" in out["error"].lower()


def test_reflect_nonexistent_file_returns_error(skill: ReflectSkill):
    out = skill.execute({"raw_query": "reflect nonexistent_note.md --insight x"})
    assert out["ok"] is False
    assert "file not found" in out["error"].lower()


# ---------------------------------------------------------------------------
# 5. _resolve_path
# ---------------------------------------------------------------------------

def test_reflect_resolve_absolute_path(tmp_path: Path, monkeypatch):
    """绝对路径直接返回。"""
    monkeypatch.setenv("CORPUS_DIR", str(tmp_path / "corpus"))
    note = tmp_path / "abs.md"
    note.write_text("# Abs\n", encoding="utf-8")
    skill = ReflectSkill()
    resolved = skill._resolve_path(str(note))
    assert resolved == note.resolve()


def test_reflect_resolve_under_corpus_root(corpus_dir: Path, skill: ReflectSkill):
    """短名 foo.md 解析到 corpus_dir/foo.md。"""
    note = corpus_dir / "short.md"
    note.write_text("# Short\n", encoding="utf-8")
    resolved = skill._resolve_path("short.md")
    assert resolved == note.resolve()


def test_reflect_resolve_via_rglob(corpus_dir: Path, skill: ReflectSkill):
    """文件名在子目录时 rglob 命中。"""
    sub = corpus_dir / "sub" / "dir"
    sub.mkdir(parents=True)
    note = sub / "nested.md"
    note.write_text("# Nested\n", encoding="utf-8")
    resolved = skill._resolve_path("nested.md")
    assert resolved == note.resolve()


def test_reflect_resolve_nonexistent_returns_none(skill: ReflectSkill):
    assert skill._resolve_path("does_not_exist.md") is None


# ---------------------------------------------------------------------------
# 6. _CMD_RE parsing
# ---------------------------------------------------------------------------

def test_cmd_re_parses_path_insight_source():
    m = _CMD_RE.match("reflect foo.md --insight my insight --source event A")
    assert m is not None
    assert m.group("path") == "foo.md"
    assert m.group("insight") == "my insight"
    assert m.group("source") == "event A"


def test_cmd_re_parses_path_only():
    m = _CMD_RE.match("reflect foo.md")
    assert m is not None
    assert m.group("path") == "foo.md"
    assert m.group("insight") is None
    assert m.group("source") is None


def test_cmd_re_parses_path_with_insight_no_source():
    m = _CMD_RE.match("reflect foo.md --insight only insight")
    assert m is not None
    assert m.group("path") == "foo.md"
    assert m.group("insight") == "only insight"
    assert m.group("source") is None


# ---------------------------------------------------------------------------
# 7. _hash_text + _parse_iso helpers
# ---------------------------------------------------------------------------

def test_hash_text_deterministic():
    assert _hash_text("foo") == _hash_text("foo")
    assert _hash_text("foo") != _hash_text("bar")


def test_hash_text_strips_whitespace():
    assert _hash_text("foo") == _hash_text("  foo  ")


def test_parse_iso_with_z_suffix():
    dt = _parse_iso("2026-01-01T00:00:00Z")
    assert dt.year == 2026
    assert dt.tzinfo is not None


def test_parse_iso_date_only():
    dt = _parse_iso("2026-01-01")
    assert dt.year == 2026
    assert dt.month == 1
    assert dt.day == 1


# ---------------------------------------------------------------------------
# 8. Atomic write
# ---------------------------------------------------------------------------

def test_reflect_atomic_write_no_tmp_left(note_path: Path, skill: ReflectSkill):
    """写入完成后不应残留 .tmp 文件。"""
    skill.execute({"raw_query": f"reflect {note_path} --insight \"x\""})
    tmp_files = list(note_path.parent.glob("*.tmp"))
    assert tmp_files == []


def test_reflect_atomic_write_preserves_on_failure(note_path: Path, skill: ReflectSkill):
    """os.replace 失败时原文件不损坏。"""
    original = note_path.read_text(encoding="utf-8")
    with patch("os.replace", side_effect=OSError("fake failure")):
        out = skill.execute({"raw_query": f"reflect {note_path} --insight x"})
    assert out["ok"] is False
    assert "write failed" in out["error"].lower()
    # 原文件未被破坏
    assert note_path.read_text(encoding="utf-8") == original
    # 清理可能残留的 .tmp
    for t in note_path.parent.glob("*.tmp"):
        t.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 9. Multiple revisions accumulate
# ---------------------------------------------------------------------------

def test_reflect_multiple_revisions_accumulate(note_path: Path, skill: ReflectSkill):
    """多次 reflect 不同 insight → revisions 数组顺序增长。"""
    for i in range(3):
        out = skill.execute({"raw_query": f"reflect {note_path} --insight 洞察{i}"})
        assert out["ok"] is True
        assert out["result"]["total_revisions"] == i + 1

    fm = skill._parse_frontmatter(note_path.read_text(encoding="utf-8"))
    insights = [rev["insight"] for rev in fm["revisions"]]
    assert insights == ["洞察0", "洞察1", "洞察2"]


# ---------------------------------------------------------------------------
# 10. File without frontmatter
# ---------------------------------------------------------------------------

def test_reflect_creates_frontmatter_if_missing(corpus_dir: Path, skill: ReflectSkill):
    """文件无 frontmatter 时，reflect 应能创建。"""
    note = corpus_dir / "no_fm.md"
    note.write_text("# No FM\n\nJust body.\n", encoding="utf-8")
    out = skill.execute({"raw_query": f"reflect {note} --insight new"})
    assert out["ok"] is True
    fm = skill._parse_frontmatter(note.read_text(encoding="utf-8"))
    assert "revisions" in fm
    assert fm["revisions"][0]["insight"] == "new"


# ---------------------------------------------------------------------------
# 11. dict-based args (fallback path)
# ---------------------------------------------------------------------------

def test_reflect_accepts_dict_args(note_path: Path, skill: ReflectSkill):
    """execute({path, insight, source}) 字典参数也能工作。"""
    out = skill.execute({
        "path": str(note_path),
        "insight": "dict insight",
        "source": "dict event",
    })
    assert out["ok"] is True
    assert out["result"]["action"] == "appended"
