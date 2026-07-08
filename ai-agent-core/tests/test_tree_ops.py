# -*- coding: utf-8 -*-
"""tests for skills.tree_ops"""
import os
import sys
import subprocess
from pathlib import Path

import pytest

from skills.tree_ops import TreeOps


# ── fixtures ────────────────────────────────────────────────────────────
@pytest.fixture
def sample_tree(tmp_path):
    (tmp_path / "file_a.py").write_text("")
    (tmp_path / "file_b.md").write_text("")
    (tmp_path / ".hidden").write_text("")
    (tmp_path / "level1").mkdir()
    (tmp_path / "level1" / "inner.txt").write_text("")
    (tmp_path / "level1" / "level2").mkdir()
    (tmp_path / "level1" / "level2" / "deep.md").write_text("")
    return tmp_path


# ── basic envelope ──────────────────────────────────────────────────────
def test_unknown_op_returns_error(sample_tree):
    out = TreeOps().execute({"op": "frobnicate", "path": str(sample_tree)})
    assert out["ok"] is False
    assert "unknown op" in out["error"].lower()


def test_missing_path_returns_error():
    out = TreeOps().execute({"op": "tree"})
    assert out["ok"] is False
    assert "missing" in out["error"].lower()


def test_nonexistent_path_returns_error():
    out = TreeOps().execute({"op": "tree", "path": "/no/such/path_xyz_123"})
    assert out["ok"] is False
    assert "not found" in out["error"].lower()


def test_file_path_returns_error(sample_tree):
    f = sample_tree / "file_a.py"
    out = TreeOps().execute({"op": "tree", "path": str(f)})
    assert out["ok"] is False
    assert "not a directory" in out["error"].lower()


def test_invalid_max_depth_returns_error(sample_tree):
    out = TreeOps().execute({"op": "tree", "path": str(sample_tree), "max_depth": -1})
    assert out["ok"] is False
    assert "max_depth" in out["error"].lower()


# ── rendering ───────────────────────────────────────────────────────────
def test_basic_render_lists_all_visible_entries(sample_tree):
    out = TreeOps().execute({"op": "tree", "path": str(sample_tree)})
    assert out["ok"] is True
    text = out["result"]
    assert "file_a.py" in text
    assert "file_b.md" in text
    assert ".hidden" not in text  # hidden by default
    assert "level1" in text
    assert "inner.txt" in text
    assert "deep.md" in text
    # summary
    assert "2 directories" in text
    assert "4 files" in text  # file_a, file_b, inner, deep


def test_dirs_only_hides_files(sample_tree):
    out = TreeOps().execute({"op": "tree", "path": str(sample_tree), "dirs_only": True})
    assert out["ok"] is True
    text = out["result"]
    assert "level1" in text
    assert "level2" in text
    assert "file_a.py" not in text
    assert "inner.txt" not in text
    assert "deep.md" not in text
    # dirs_only: report should not include "files" count
    last_line = text.split("\n")[-1]
    assert "files" not in last_line


def test_all_files_shows_hidden(sample_tree):
    out = TreeOps().execute({"op": "tree", "path": str(sample_tree), "all_files": True})
    assert out["ok"] is True
    assert ".hidden" in out["result"]


def test_max_depth_truncates(sample_tree):
    out = TreeOps().execute({"op": "tree", "path": str(sample_tree), "max_depth": 1})
    assert out["ok"] is True
    text = out["result"]
    assert "file_a.py" in text
    assert "level1" in text
    # level1's children should not be rendered at depth 1
    assert "inner.txt" not in text
    assert "deep.md" not in text


def test_tree_characters_present(sample_tree):
    out = TreeOps().execute({"op": "tree", "path": str(sample_tree)})
    text = out["result"]
    # at least one of each connector
    assert "├──" in text or "└──" in text
    # no leading/trailing whitespace per line (except root)
    for line in text.split("\n"):
        if line:
            assert not line.startswith("\t")


# ── pattern / ignore ────────────────────────────────────────────────────
def test_pattern_filters_files_only(sample_tree):
    out = TreeOps().execute({"op": "tree", "path": str(sample_tree), "pattern": "*.py"})
    assert out["ok"] is True
    text = out["result"]
    assert "file_a.py" in text
    assert "file_b.md" not in text
    # directories still shown even if their files don't match
    assert "level1" in text


def test_ignore_excludes_matching(sample_tree):
    out = TreeOps().execute({"op": "tree", "path": str(sample_tree), "ignore": "*.md"})
    assert out["ok"] is True
    text = out["result"]
    assert "file_b.md" not in text
    assert "deep.md" not in text
    assert "file_a.py" in text


# ── raw mode ────────────────────────────────────────────────────────────
def test_raw_returns_structured_data(sample_tree):
    out = TreeOps().execute({"op": "tree", "path": str(sample_tree), "raw": True})
    assert out["ok"] is True
    result = out["result"]
    assert isinstance(result, dict)
    assert "tree" in result
    assert "dirs" in result
    assert "files" in result
    assert isinstance(result["tree"], dict)
    assert result["dirs"] >= 2
    assert result["files"] >= 3


# ── size display ────────────────────────────────────────────────────────
def test_show_size_appends_bracket(sample_tree):
    (sample_tree / "file_a.py").write_text("x" * 100)
    out = TreeOps().execute({
        "op": "tree", "path": str(sample_tree), "show_size": True,
    })
    assert out["ok"] is True
    assert "[100]" in out["result"]


def test_human_size_formats_readably(sample_tree):
    (sample_tree / "file_a.py").write_text("x" * 2048)
    out = TreeOps().execute({
        "op": "tree", "path": str(sample_tree),
        "show_size": True, "human_size": True,
    })
    assert out["ok"] is True
    assert "K" in out["result"]  # 2048 B = 2.0K


# ── noreport ────────────────────────────────────────────────────────────
def test_noreport_suppresses_summary(sample_tree):
    out = TreeOps().execute({"op": "tree", "path": str(sample_tree), "noreport": True})
    assert out["ok"] is True
    text = out["result"]
    assert "directories" not in text
    assert "files" not in text


# ── empty dir ───────────────────────────────────────────────────────────
def test_empty_dir_renders_without_error(tmp_path):
    (tmp_path / "empty_subdir").mkdir()
    out = TreeOps().execute({"op": "tree", "path": str(tmp_path)})
    assert out["ok"] is True
    assert "empty_subdir" in out["result"]


# ── permission denied ──────────────────────────────────────────────────
@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses permissions")
def test_permission_denied_does_not_crash(tmp_path):
    sub = tmp_path / "noperm"
    sub.mkdir()
    (sub / "secret.txt").write_text("top secret")
    os.chmod(sub, 0o000)
    try:
        out = TreeOps().execute({"op": "tree", "path": str(tmp_path)})
        assert out["ok"] is True
        # should still render, with error marker on the locked dir
        assert "noperm" in out["result"]
    finally:
        os.chmod(sub, 0o755)


# ── CLI entry ───────────────────────────────────────────────────────────
def test_cli_runs_via_subprocess(sample_tree):
    script = Path(__file__).parent.parent / "skills" / "tree_ops.py"
    proc = subprocess.run(
        [sys.executable, str(script), "-L", "1", str(sample_tree)],
        capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0
    assert "level1" in proc.stdout
    # depth 1 means inner.txt should not appear
    assert "inner.txt" not in proc.stdout


def test_cli_nonexistent_path_exits_nonzero():
    script = Path(__file__).parent.parent / "skills" / "tree_ops.py"
    proc = subprocess.run(
        [sys.executable, str(script), "/no/such/path_xyz_123"],
        capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 1
    assert "not found" in proc.stderr.lower()


def test_cli_help_flag_exits_zero():
    script = Path(__file__).parent.parent / "skills" / "tree_ops.py"
    proc = subprocess.run(
        [sys.executable, str(script), "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0
    assert "usage" in proc.stderr.lower()
