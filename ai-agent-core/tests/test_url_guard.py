"""Phase 1 tests — M8 URL guard + authorization + path safety."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from harness.bot.url_guard import (
    is_authorized,
    is_safe_url,
    safe_corpus_path,
    sanitize_filename,
)


class TestIsAuthorized:
    def test_empty_denies_all(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "")
        assert not is_authorized(123)
        assert not is_authorized(0)

    def test_wildcard_allows_all(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "*")
        assert is_authorized(123)
        assert is_authorized(0)

    def test_explicit_list(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "111,222,333")
        assert is_authorized(111)
        assert is_authorized(333)
        assert not is_authorized(444)

    def test_whitespace_tolerant(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", " 111 , 222 ")
        assert is_authorized(111)
        assert is_authorized(222)
        assert not is_authorized(333)

    def test_explicit_raw_overrides_env(self):
        assert is_authorized(5, raw="5,6")
        assert not is_authorized(7, raw="5,6")

    def test_non_digit_entries_ignored(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "abc,111,xyz")
        assert is_authorized(111)
        assert not is_authorized(999)


class TestSanitizeFilename:
    def test_strips_path_prefix(self):
        assert sanitize_filename("../../etc/passwd") == "passwd"

    def test_strips_absolute_path(self):
        assert sanitize_filename("/etc/shadow") == "shadow"

    def test_plain_name_unchanged(self):
        assert sanitize_filename("report.pdf") == "report.pdf"

    def test_empty_falls_back_to_unnamed(self):
        assert sanitize_filename("") == "unnamed"


class TestSafeCorpusPath:
    def test_path_inside_corpus(self, tmp_path: Path):
        root = tmp_path / "corpus"
        root.mkdir()
        f = root / "a.md"
        f.write_text("x")
        result = safe_corpus_path(str(f), corpus_root=str(root))
        assert result is not None
        assert result.resolve() == f.resolve()

    def test_path_traversal_rejected(self, tmp_path: Path):
        root = tmp_path / "corpus"
        root.mkdir()
        # Create a file outside corpus
        outside = tmp_path / "secret.txt"
        outside.write_text("x")
        bad = str(root / ".." / "secret.txt")
        assert safe_corpus_path(bad, corpus_root=str(root)) is None

    def test_symlink_rejected(self, tmp_path: Path):
        root = tmp_path / "corpus"
        root.mkdir()
        target = tmp_path / "outside.md"
        target.write_text("x")
        link = root / "link.md"
        link.symlink_to(target)
        assert safe_corpus_path(str(link), corpus_root=str(root)) is None


class TestIsSafeUrl:
    def test_missing_host_rejected(self):
        assert not is_safe_url("not a url")

    def test_loopback_ipv4_rejected(self):
        assert not is_safe_url("http://127.0.0.1/admin")

    def test_loopback_ipv6_rejected(self):
        assert not is_safe_url("http://[::1]/x")

    def test_private_10_rejected(self):
        assert not is_safe_url("http://10.0.0.1/x")

    def test_metadata_endpoint_rejected(self):
        assert not is_safe_url("http://169.254.169.254/latest/meta-data/")

    def test_invalid_hostname_rejected(self):
        assert not is_safe_url("http://this-host-does-not-exist.invalid/x")
