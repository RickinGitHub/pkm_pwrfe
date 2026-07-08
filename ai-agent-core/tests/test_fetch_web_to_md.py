"""fetch_web_to_md Skill 测试 — 不依赖网络，使用 monkeypatch mock http_get."""
import os
from unittest.mock import patch
from skills.fetch_web_to_md import (
    FetchWebToMd,
    extract_attachments,
    rewrite_local_paths,
    download_attachments,
)


_FAKE_HTML = """
<html><head>
<meta property="og:title" content="Test Article"/>
<meta property="article:author" content="Tester"/>
</head><body>
<div id="js_content"><h1>Hello</h1><p>World <a href="https://x.com">x</a></p>
<img src="http://img.com/a.png" alt="pic"/></div>
</body></html>
"""

_FAKE_HTML_WITH_ATTACHMENTS = """
<html><head>
<meta property="og:title" content="Doc with Attachments"/>
</head><body>
<div id="js_content">
<p>正文 <a href="https://example.com/paper.pdf">论文 PDF</a></p>
<p><a href="https://example.com/data.zip">数据包</a></p>
<p><a href="https://example.com/video.mp4">视频</a></p>
<p><a href="https://example.com/page">普通链接（不应被识别为附件）</a></p>
<img src="http://img.com/a.png" alt="pic"/>
</div>
</body></html>
"""


def test_unknown_op_returns_error():
    out = FetchWebToMd().execute({"op": "frob", "url": "https://x.com"})
    assert out["ok"] is False
    assert "unknown op" in out["error"].lower()


def test_missing_url_returns_error():
    out = FetchWebToMd().execute({"op": "fetch"})
    assert out["ok"] is False
    assert "url" in out["error"].lower()


def test_invalid_url_scheme_returns_error():
    out = FetchWebToMd().execute({"op": "fetch", "url": "ftp://x.com"})
    assert out["ok"] is False
    assert "http" in out["error"].lower()


def test_invalid_format_returns_error():
    out = FetchWebToMd().execute({"op": "fetch", "url": "https://x.com", "format": "pdf"})
    assert out["ok"] is False
    assert "format" in out["error"].lower()


def test_invalid_timeout_returns_error():
    out = FetchWebToMd().execute({"op": "fetch", "url": "https://x.com", "timeout": -1})
    assert out["ok"] is False
    assert "timeout" in out["error"].lower()


def test_fetch_wechat_success(tmp_path):
    out_dir = str(tmp_path)
    with patch("skills.fetch_web_to_md.http_get", return_value=(_FAKE_HTML, "https://mp.weixin.qq.com/s/x", {})):
        out = FetchWebToMd().execute({
            "op": "fetch",
            "url": "https://mp.weixin.qq.com/s/x",
            "format": "md",
            "output_path": out_dir,
        })
    assert out["ok"] is True, out.get("error")
    assert out["result"]["title"] == "Test Article"
    assert out["result"]["author"] == "Tester"
    assert out["result"]["chars"] > 0
    assert out["result"]["source_type"] == "wechat"
    # filename based on title
    assert out["result"]["filepath"].endswith("Test Article.md")


def test_fetch_json_format(tmp_path):
    out_dir = str(tmp_path)
    with patch("skills.fetch_web_to_md.http_get", return_value=(_FAKE_HTML, "https://x.com", {})):
        out = FetchWebToMd().execute({
            "op": "fetch",
            "url": "https://x.com",
            "format": "json",
            "output_path": out_dir,
        })
    assert out["ok"] is True, out.get("error")
    assert out["result"]["format"] == "json"
    assert out["result"]["filepath"].endswith("Test Article.json")


def test_fetch_html_format(tmp_path):
    out_dir = str(tmp_path)
    with patch("skills.fetch_web_to_md.http_get", return_value=(_FAKE_HTML, "https://x.com", {})):
        out = FetchWebToMd().execute({
            "op": "fetch",
            "url": "https://x.com",
            "format": "html",
            "output_path": out_dir,
        })
    assert out["ok"] is True, out.get("error")
    assert out["result"]["filepath"].endswith("Test Article.html")


def test_fetch_handles_http_error():
    with patch("skills.fetch_web_to_md.http_get", side_effect=Exception("network down")):
        out = FetchWebToMd().execute({
            "op": "fetch",
            "url": "https://x.com",
        })
    assert out["ok"] is False
    assert "network down" in out["error"]


def test_links_only_mode_returns_link_list():
    with patch("skills.fetch_web_to_md.http_get", return_value=(_FAKE_HTML, "https://x.com", {})):
        out = FetchWebToMd().execute({
            "op": "fetch",
            "url": "https://x.com",
            "links_only": True,
        })
    assert out["ok"] is True
    assert out["result"]["url"] == "https://x.com"
    assert isinstance(out["result"]["links"], list)
    assert any(l["href"] == "https://x.com" for l in out["result"]["links"])


def test_agent_routes_fetch_command_to_skill(tmp_path):
    """端到端：'fetch <url>' 经 AgentCore 路由到 fetch_web skill."""
    import yaml
    from agent import AgentCore

    rules = {"role": "test", "max_output_tokens": 256, "prompt_prefix": "x", "output_format": "json"}
    routing = {"entries": [
        {"intent": "^fetch.*http", "tool_type": "skill", "tool_name": "fetch_web", "fallback": None},
        {"intent": ".*", "tool_type": "llm", "tool_name": "claude", "fallback": None},
    ]}
    rp = tmp_path / "rules.yaml"
    rp.write_text(yaml.safe_dump(rules))
    up = tmp_path / "routing.yaml"
    up.write_text(yaml.safe_dump(routing))

    agent = AgentCore(
        rules_path=str(rp),
        routing_path=str(up),
        cache_path=str(tmp_path / "c.db"),
        short_term_path=str(tmp_path / "st.json"),
        long_term_path=str(tmp_path / "lt.db"),
    )
    agent.register_skill("fetch_web", FetchWebToMd())

    with patch("skills.fetch_web_to_md.http_get", return_value=(_FAKE_HTML, "https://x.com", {})):
        out = agent.handle("fetch https://x.com")

    assert out["ok"] is True, out.get("error")
    assert out["result"]["source_type"] in ("wechat", "web")


def test_agent_parse_skill_args_extracts_url():
    """_parse_skill_args 正确解析 'fetch <url>'."""
    from agent import AgentCore
    import yaml
    import tempfile
    from pathlib import Path

    rules = {"role": "t", "max_output_tokens": 64, "prompt_prefix": "x", "output_format": "json"}
    routing = {"entries": [{"intent": ".*", "tool_type": "llm", "tool_name": "c", "fallback": None}]}
    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        (p / "rules.yaml").write_text(yaml.safe_dump(rules))
        (p / "routing.yaml").write_text(yaml.safe_dump(routing))
        agent = AgentCore(str(p / "rules.yaml"), str(p / "routing.yaml"), str(p / "c.db"), str(p / "st.json"), str(p / "lt.db"))
        args = agent._parse_skill_args("fetch https://example.com/page")
        assert args == {"op": "fetch", "url": "https://example.com/page"}

        args2 = agent._parse_skill_args("crawl https://x.com")
        assert args2 == {"op": "fetch", "url": "https://x.com"}


# ---------------------------------------------------------------------------
# extract_attachments — P0 附件识别
# ---------------------------------------------------------------------------

def test_extract_attachments_finds_pdf_zip_mp4():
    html = """
    <a href="https://example.com/paper.pdf">论文</a>
    <a href="https://example.com/data.zip">数据</a>
    <a href="https://example.com/video.mp4">视频</a>
    """
    atts = extract_attachments(html)
    srcs = [a['src'] for a in atts]
    assert "https://example.com/paper.pdf" in srcs
    assert "https://example.com/data.zip" in srcs
    assert "https://example.com/video.mp4" in srcs
    exts = {a['ext'] for a in atts}
    assert exts == {".pdf", ".zip", ".mp4"}


def test_extract_attachments_skips_non_file_links():
    html = """
    <a href="https://example.com/page">普通页面</a>
    <a href="https://example.com/article.html">HTML 页</a>
    <a href="/relative/path.pdf">相对路径（应跳过）</a>
    """
    atts = extract_attachments(html)
    assert atts == []


def test_extract_attachments_deduplicates_same_url():
    html = """
    <a href="https://example.com/doc.pdf">A</a>
    <a href="https://example.com/doc.pdf">B</a>
    """
    atts = extract_attachments(html)
    assert len(atts) == 1


def test_extract_attachments_covers_all_ext_in_list():
    html = '<a href="https://x.com/a.docx">d</a><a href="https://x.com/b.xlsx">s</a><a href="https://x.com/c.pptx">p</a>'
    exts = {a['ext'] for a in extract_attachments(html)}
    assert exts == {".docx", ".xlsx", ".pptx"}


# ---------------------------------------------------------------------------
# rewrite_local_paths — P0 .md URL 改写
# ---------------------------------------------------------------------------

def test_rewrite_local_paths_replaces_image_urls():
    content = "![pic](http://img.com/a.png)\nbody"
    images = [{"src": "http://img.com/a.png", "local_path": "/out/images/foo_img1.png", "status": "ok"}]
    out = rewrite_local_paths(content, images=images)
    assert "http://img.com/a.png" not in out
    assert "images/foo_img1.png" in out


def test_rewrite_local_paths_skips_failed_downloads():
    content = "![pic](http://img.com/a.png)\nbody"
    images = [{"src": "http://img.com/a.png", "local_path": "/out/images/foo.png", "status": "error: timeout"}]
    out = rewrite_local_paths(content, images=images)
    # Failed downloads keep remote URL
    assert "http://img.com/a.png" in out


def test_rewrite_local_paths_replaces_attachment_urls():
    content = "[论文](https://example.com/paper.pdf)"
    atts = [{"src": "https://example.com/paper.pdf", "local_path": "/out/attachments/foo_att1_论文.pdf", "status": "ok"}]
    out = rewrite_local_paths(content, attachments=atts)
    assert "https://example.com/paper.pdf" not in out
    assert "attachments/foo_att1_论文.pdf" in out


def test_rewrite_local_paths_handles_empty_input():
    assert rewrite_local_paths("", images=None) == ""
    assert rewrite_local_paths("body", images=None, attachments=None) == "body"


# ---------------------------------------------------------------------------
# download_attachments — P0 附件下载（mock urlretrieve）
# ---------------------------------------------------------------------------

def test_download_attachments_returns_empty_for_empty_list(tmp_path):
    assert download_attachments([], str(tmp_path)) == []


def test_download_attachments_handles_no_urllib(tmp_path):
    # Force HAS_URLLIB False path
    import skills.fetch_web_to_md as mod
    orig = mod.HAS_URLLIB
    mod.HAS_URLLIB = False
    try:
        out = download_attachments([{"src": "https://x.com/a.pdf", "text": "a", "ext": ".pdf"}], str(tmp_path))
        assert out == []
    finally:
        mod.HAS_URLLIB = orig


def test_download_attachments_invokes_urlretrieve(tmp_path):
    from unittest.mock import patch
    atts = [
        {"src": "https://example.com/paper.pdf", "text": "论文", "ext": ".pdf"},
        {"src": "https://example.com/data.zip", "text": "数据", "ext": ".zip"},
    ]
    with patch("skills.fetch_web_to_md.urlretrieve") as mock_retrieve:
        mock_retrieve.return_value = None
        results = download_attachments(atts, str(tmp_path), prefix="doc")
    assert len(results) == 2
    assert all(r["status"] == "ok" for r in results)
    # Filename: <prefix>_att<N>_<safe_text><ext>
    assert results[0]["local_path"].endswith(".pdf")
    assert "doc_att1" in results[0]["local_path"]
    assert results[1]["local_path"].endswith(".zip")
    assert mock_retrieve.call_count == 2


def test_download_attachments_records_errors(tmp_path):
    from unittest.mock import patch
    atts = [{"src": "https://x.com/missing.pdf", "text": "miss", "ext": ".pdf"}]
    with patch("skills.fetch_web_to_md.urlretrieve", side_effect=IOError("404")):
        results = download_attachments(atts, str(tmp_path))
    assert len(results) == 1
    assert "error" in results[0]["status"]
    assert results[0]["status"] != "ok"


# ---------------------------------------------------------------------------
# FetchWebToMd.execute — 集成层验证
# ---------------------------------------------------------------------------

def test_fetch_extracts_attachments_in_result(tmp_path):
    out_dir = str(tmp_path)
    with patch("skills.fetch_web_to_md.http_get",
               return_value=(_FAKE_HTML_WITH_ATTACHMENTS, "https://x.com", {})):
        out = FetchWebToMd().execute({
            "op": "fetch",
            "url": "https://x.com",
            "format": "md",
            "output_path": out_dir,
        })
    assert out["ok"] is True, out.get("error")
    assert out["result"]["attachments_count"] == 3  # pdf, zip, mp4 — not the .html link


def test_fetch_save_attachments_downloads_and_rewrites_urls(tmp_path):
    out_dir = str(tmp_path)
    with patch("skills.fetch_web_to_md.http_get",
               return_value=(_FAKE_HTML_WITH_ATTACHMENTS, "https://x.com", {})):
        with patch("skills.fetch_web_to_md.urlretrieve") as mock_retrieve:
            mock_retrieve.return_value = None
            out = FetchWebToMd().execute({
                "op": "fetch",
                "url": "https://x.com",
                "format": "md",
                "output_path": out_dir,
                "save_attachments": True,
            })
    assert out["ok"] is True, out.get("error")
    assert out["result"]["attachments_downloaded"] == 3
    assert mock_retrieve.call_count == 3
    # .md should have local relative paths, not remote URLs
    md_path = out["result"]["filepath"]
    md = open(md_path, encoding="utf-8").read()
    assert "https://example.com/paper.pdf" not in md
    assert "attachments/" in md
    # attachments/ subdir was created
    assert (tmp_path / "attachments").is_dir()


def test_fetch_save_img_rewrites_image_urls_in_md(tmp_path):
    out_dir = str(tmp_path)
    with patch("skills.fetch_web_to_md.http_get",
               return_value=(_FAKE_HTML, "https://mp.weixin.qq.com/s/x", {})):
        with patch("skills.fetch_web_to_md.urlretrieve") as mock_retrieve:
            mock_retrieve.return_value = None
            out = FetchWebToMd().execute({
                "op": "fetch",
                "url": "https://mp.weixin.qq.com/s/x",
                "format": "md",
                "output_path": out_dir,
                "save_img": True,
            })
    assert out["ok"] is True
    assert out["result"]["images_downloaded"] == 1
    md_path = out["result"]["filepath"]
    md = open(md_path, encoding="utf-8").read()
    assert "http://img.com/a.png" not in md  # remote URL rewritten
    assert "images/" in md
    assert (tmp_path / "images").is_dir()


def test_fetch_without_save_flags_keeps_remote_urls(tmp_path):
    out_dir = str(tmp_path)
    with patch("skills.fetch_web_to_md.http_get",
               return_value=(_FAKE_HTML, "https://mp.weixin.qq.com/s/x", {})):
        out = FetchWebToMd().execute({
            "op": "fetch",
            "url": "https://mp.weixin.qq.com/s/x",
            "format": "md",
            "output_path": out_dir,
        })
    assert out["ok"] is True
    md_path = out["result"]["filepath"]
    md = open(md_path, encoding="utf-8").read()
    assert "http://img.com/a.png" in md  # remote URL preserved
    assert not (tmp_path / "images").is_dir()


# ---------------------------------------------------------------------------
# iframe / video / audio → 可点击链接占位（P1/P2 全部走占位策略）
# ---------------------------------------------------------------------------

_FAKE_HTML_WITH_MEDIA = """
<html><head><meta property="og:title" content="Media Doc"/></head><body>
<div id="js_content">
<p>正文</p>
<iframe src="https://www.youtube.com/embed/abc"></iframe>
<video src="https://example.com/clip.mp4" controls></video>
<audio src="https://example.com/song.mp3" controls></audio>
<video controls><source src="https://example.com/clip2.webm" type="video/webm"/></video>
<embed src="https://example.com/swf.swf">
</div>
</body></html>
"""

def test_iframe_converted_to_clickable_link(tmp_path):
    out_dir = str(tmp_path)
    with patch("skills.fetch_web_to_md.http_get",
               return_value=(_FAKE_HTML_WITH_MEDIA, "https://x.com", {})):
        out = FetchWebToMd().execute({
            "op": "fetch", "url": "https://x.com",
            "format": "md", "output_path": out_dir,
        })
    assert out["ok"] is True
    md_path = out["result"]["filepath"]
    md = open(md_path, encoding="utf-8").read()
    # iframe URL 应作为可点击 Markdown 链接出现
    assert "https://www.youtube.com/embed/abc" in md
    # 不应残留旧的纯文字占位
    assert "[Embedded Content]" not in md
    # 应该有可点击链接格式
    assert "[📎" in md


def test_video_audio_converted_to_clickable_links(tmp_path):
    out_dir = str(tmp_path)
    with patch("skills.fetch_web_to_md.http_get",
               return_value=(_FAKE_HTML_WITH_MEDIA, "https://x.com", {})):
        out = FetchWebToMd().execute({
            "op": "fetch", "url": "https://x.com",
            "format": "md", "output_path": out_dir,
        })
    assert out["ok"] is True
    md_path = out["result"]["filepath"]
    md = open(md_path, encoding="utf-8").read()
    # video / audio / source / embed 的 URL 全部保留为可点击链接
    assert "https://example.com/clip.mp4" in md
    assert "https://example.com/song.mp3" in md
    assert "https://example.com/clip2.webm" in md
    assert "https://example.com/swf.swf" in md
    # 标签符号
    assert "[📎 Video]" in md
    assert "[📎 Audio]" in md


def test_filename_based_on_title_no_timestamp(tmp_path):
    """文件名基于原文 title，无时间戳前缀。"""
    out_dir = str(tmp_path)
    with patch("skills.fetch_web_to_md.http_get",
               return_value=(_FAKE_HTML, "https://x.com", {})):
        out = FetchWebToMd().execute({
            "op": "fetch", "url": "https://x.com",
            "format": "md", "output_path": out_dir,
        })
    assert out["ok"] is True
    filepath = out["result"]["filepath"]
    assert filepath.endswith("Test Article.md")
    # 不应含 YYYYMMDD_HHMMSS_ 前缀
    import re
    basename = os.path.basename(filepath)
    assert not re.match(r"^\d{8}_\d{6}_", basename)


def test_output_path_accepts_relative(tmp_path, monkeypatch):
    """--path 接受相对路径（相对于 cwd）。"""
    monkeypatch.chdir(tmp_path)
    rel_dir = "subdir"
    with patch("skills.fetch_web_to_md.http_get",
               return_value=(_FAKE_HTML, "https://x.com", {})):
        out = FetchWebToMd().execute({
            "op": "fetch", "url": "https://x.com",
            "format": "md", "output_path": rel_dir,
        })
    assert out["ok"] is True
    filepath = out["result"]["filepath"]
    assert filepath.startswith(str(tmp_path / "subdir"))
    assert (tmp_path / "subdir" / "Test Article.md").is_file()
