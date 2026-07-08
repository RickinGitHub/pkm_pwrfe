"""Tests for scripts.pipeline_worker.clean_md."""

from scripts.pipeline_worker import clean_md


def test_clean_strips_script_and_style_blocks():
    text = "# Title\n\n<script>alert('x')</script>\n\n<style>body{}</style>\n\nbody"
    out = clean_md(text)
    assert "<script>" not in out
    assert "<style>" not in out
    assert "alert" not in out
    assert "body{}" not in out
    assert "body" in out


def test_clean_strips_html_tags_but_keeps_text():
    text = "# Hello\n\n<div>world</div>\n\n<span>foo</span>"
    out = clean_md(text)
    assert "<div>" not in out
    assert "<span>" not in out
    assert "world" in out
    assert "foo" in out


def test_clean_protects_code_blocks_from_html_stripping():
    text = "# T\n\n```html\n<div>keep me</div>\n```\n\n<div>strip me</div>"
    out = clean_md(text)
    assert "keep me" in out
    assert "strip me" in out
    assert out.count("<div>") == 1  # only the one inside code block


def test_clean_collapses_excess_whitespace():
    text = "# T\n\n\n\n\npara1\n\n\n\npara2   \n   \n  "
    out = clean_md(text)
    assert "\n\n\n" not in out
    assert "para1\n\npara2" in out
    assert not out.endswith("   ")


def test_clean_truncates_long_text_at_paragraph_boundary():
    para = "x" * 2000
    text = "\n\n".join([para] * 50)  # ~100k chars
    out = clean_md(text, max_chars=5000)
    assert len(out) < 6000
    assert out.endswith("[...truncated...]\n")


def test_clean_truncates_when_no_paragraph_boundary_near_max():
    text = "x" * 50000
    out = clean_md(text, max_chars=5000)
    assert len(out) < 6000
    assert "[...truncated...]" in out


def test_clean_handles_empty_input():
    assert clean_md("") == ""


def test_clean_preserves_markdown_structure():
    text = "# H1\n\n## H2\n\n- item1\n- item2\n\n**bold** *italic*"
    out = clean_md(text)
    assert "# H1" in out
    assert "## H2" in out
    assert "- item1" in out
    assert "**bold**" in out
