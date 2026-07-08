# -*- coding: utf-8 -*-
"""P0-2: URL → path dedup registry + fetch_web integration."""
from unittest.mock import patch

from memories.url_registry import UrlRegistry
from skills.fetch_web_to_md import FetchWebToMd


_FAKE_HTML = """
<html><head>
<meta property="og:title" content="Dedup Test"/>
</head><body>
<div id="js_content"><p>Hello world.</p></div>
</body></html>
"""


def test_url_registry_record_and_lookup(tmp_path):
    reg = UrlRegistry(str(tmp_path / "urls.db"))
    reg.record("https://x.com/a", "out/a.md", "A")
    hit = reg.lookup("https://x.com/a")
    assert hit is not None
    assert hit["filepath"] == "out/a.md"
    assert hit["title"] == "A"
    assert hit["fetched_at"]


def test_url_registry_missing_returns_none(tmp_path):
    reg = UrlRegistry(str(tmp_path / "urls.db"))
    assert reg.lookup("https://nope.example") is None


def test_url_registry_record_upserts(tmp_path):
    reg = UrlRegistry(str(tmp_path / "urls.db"))
    reg.record("https://x.com/a", "a.md", "A")
    reg.record("https://x.com/a", "b.md", "B")  # update
    assert reg.count() == 1
    hit = reg.lookup("https://x.com/a")
    assert hit["filepath"] == "b.md"
    assert hit["title"] == "B"


def test_fetch_dedup_returns_cached_path(tmp_path):
    reg = UrlRegistry(str(tmp_path / "urls.db"))
    # Pre-populate registry as if we'd already fetched this URL
    cached_path = str(tmp_path / "cached.md")
    with open(cached_path, "w") as f:
        f.write("# cached")
    reg.record("https://example.com/article", cached_path, "Cached Title")

    skill = FetchWebToMd(url_registry=reg)
    out = skill.execute({
        "op": "fetch",
        "url": "https://example.com/article",
        "format": "md",
        "output_path": str(tmp_path),
    })
    assert out["ok"] is True, out.get("error")
    assert out["result"]["filepath"] == cached_path
    assert out["result"]["source_type"] == "cached"
    assert out["result"].get("deduped") is True


def test_fetch_force_bypasses_dedup(tmp_path):
    reg = UrlRegistry(str(tmp_path / "urls.db"))
    cached_path = str(tmp_path / "cached.md")
    with open(cached_path, "w") as f:
        f.write("# cached")
    reg.record("https://example.com/x", cached_path, "Cached")

    skill = FetchWebToMd(url_registry=reg)
    with patch("skills.fetch_web_to_md.http_get", return_value=(_FAKE_HTML, "https://example.com/x", {})):
        out = skill.execute({
            "op": "fetch",
            "url": "https://example.com/x",
            "format": "md",
            "output_path": str(tmp_path),
            "force": True,
        })
    assert out["ok"] is True, out.get("error")
    # Should have actually fetched (not returned cached path)
    assert out["result"]["source_type"] != "cached"
    assert out["result"]["title"] == "Dedup Test"


def test_fetch_records_url_after_successful_fetch(tmp_path):
    reg = UrlRegistry(str(tmp_path / "urls.db"))
    skill = FetchWebToMd(url_registry=reg)
    with patch("skills.fetch_web_to_md.http_get", return_value=(_FAKE_HTML, "https://example.com/new", {})):
        out = skill.execute({
            "op": "fetch",
            "url": "https://example.com/new",
            "format": "md",
            "output_path": str(tmp_path),
        })
    assert out["ok"] is True, out.get("error")
    hit = reg.lookup("https://example.com/new")
    assert hit is not None
    assert hit["filepath"].endswith("Dedup Test.md")


def test_fetch_dedup_skipped_when_file_missing(tmp_path):
    """If the cached file no longer exists, fetch should re-download."""
    reg = UrlRegistry(str(tmp_path / "urls.db"))
    reg.record("https://example.com/gone", str(tmp_path / "missing.md"), "Gone")

    skill = FetchWebToMd(url_registry=reg)
    with patch("skills.fetch_web_to_md.http_get", return_value=(_FAKE_HTML, "https://example.com/gone", {})):
        out = skill.execute({
            "op": "fetch",
            "url": "https://example.com/gone",
            "format": "md",
            "output_path": str(tmp_path),
        })
    assert out["ok"] is True, out.get("error")
    assert out["result"]["source_type"] != "cached"
