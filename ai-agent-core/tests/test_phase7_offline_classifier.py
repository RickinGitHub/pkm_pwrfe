"""Phase 7 tests: offline LLM classifier (Ollama integration).

Covers classify_hook fallback logic, classify_with_ollama HTTP/parse,
failure modes (timeout, HTTP error, unparseable response).
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.offline_classifier import (
    _load_tag_rules,
    classify_hook,
    classify_with_ollama,
)


# ---------------------------------------------------------------------------
# _load_tag_rules
# ---------------------------------------------------------------------------

def test_load_tag_rules_returns_dict_with_l1_tags(tmp_path: Path):
    rules_yaml = tmp_path / "rules.yaml"
    rules_yaml.write_text(
        "defaults:\n  l1: 未分类\n  l2: Misc\n  l3: General\n"
        "rules:\n"
        "  - l1: 科技\n    l2: AI\n    l3: 模型\n    keywords: [ai]\n"
        "  - l1: 历史\n    l2: 中国\n    l3: 朝代\n    keywords: [汉]\n",
        encoding="utf-8",
    )
    tags = _load_tag_rules(str(rules_yaml))
    assert "l1_tags" in tags
    assert "tag_map" in tags
    assert "科技" in tags["l1_tags"]
    assert "历史" in tags["l1_tags"]
    assert "未分类" in tags["l1_tags"]


def test_load_tag_rules_handles_missing_file():
    tags = _load_tag_rules("/nonexistent/path.yaml")
    assert tags == {"l1_tags": [], "tag_map": ""}


# ---------------------------------------------------------------------------
# classify_hook — fallback logic
# ---------------------------------------------------------------------------

def test_classify_hook_returns_rules_when_disabled(monkeypatch):
    """OLLAMA_CLASSIFY_ENABLED=0 时直接返回 rules_result。"""
    monkeypatch.setenv("OLLAMA_CLASSIFY_ENABLED", "0")
    rules_result = ("科技", "AI", "模型")
    out = classify_hook("title", "content", rules_result)
    assert out == rules_result


def test_classify_hook_returns_rules_when_ollama_fails(monkeypatch):
    """Ollama 返回 None → hook 回退到 rules_result。"""
    monkeypatch.setenv("OLLAMA_CLASSIFY_ENABLED", "1")
    rules_result = ("科技", "AI", "模型")
    with patch("scripts.offline_classifier.classify_with_ollama", return_value=None):
        out = classify_hook("title", "content", rules_result)
    assert out == rules_result


def test_classify_hook_returns_rules_when_ollama_unclassified(monkeypatch):
    """Ollama 返回 ('未分类', '', '') → hook 回退到规则。"""
    monkeypatch.setenv("OLLAMA_CLASSIFY_ENABLED", "1")
    rules_result = ("科技", "AI", "模型")
    with patch("scripts.offline_classifier.classify_with_ollama",
               return_value=("未分类", "", "")):
        out = classify_hook("title", "content", rules_result)
    assert out == rules_result


def test_classify_hook_returns_rules_when_ollama_misc(monkeypatch):
    """Ollama 返回 l2=='Misc' → hook 回退到规则。"""
    monkeypatch.setenv("OLLAMA_CLASSIFY_ENABLED", "1")
    rules_result = ("科技", "AI", "模型")
    with patch("scripts.offline_classifier.classify_with_ollama",
               return_value=("历史", "Misc", "General")):
        out = classify_hook("title", "content", rules_result)
    assert out == rules_result


def test_classify_hook_returns_ollama_when_valid(monkeypatch):
    """Ollama 返回有效分类 → hook 透传。"""
    monkeypatch.setenv("OLLAMA_CLASSIFY_ENABLED", "1")
    rules_result = ("未分类", "Misc", "General")
    with patch("scripts.offline_classifier.classify_with_ollama",
               return_value=("历史", "中国", "朝代")):
        out = classify_hook("title", "content", rules_result)
    assert out == ("历史", "中国", "朝代")


# ---------------------------------------------------------------------------
# classify_with_ollama — HTTP + JSON parsing
# ---------------------------------------------------------------------------

def _mock_urlopen_response(payload: dict):
    """Build a mock urlopen context manager returning JSON payload."""
    body = json.dumps(payload).encode("utf-8")
    mock_resp = io.BytesIO(body)
    mock_resp.__enter__ = lambda *a: mock_resp
    mock_resp.__exit__ = lambda *a: False
    mock_resp.read = lambda: body
    return mock_resp


def test_classify_with_ollama_parses_json_response(monkeypatch):
    """mock HTTP 200 + JSON {response: '{"l1":...}'} → 返回元组。"""
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:3b")
    monkeypatch.setenv("OLLAMA_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_CLASSIFY_TIMEOUT", "5")

    mock_resp = _mock_urlopen_response({
        "response": '{"l1": "历史", "l2": "中国", "l3": "朝代"}'
    })
    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = classify_with_ollama("title", "content")
    assert result == ("历史", "中国", "朝代")


def test_classify_with_ollama_parses_embedded_json(monkeypatch):
    """响应含 markdown code fence → regex 提取 JSON。"""
    monkeypatch.setenv("OLLAMA_CLASSIFY_TIMEOUT", "5")
    mock_resp = _mock_urlopen_response({
        "response": 'Sure! Here is my classification:\n```json\n{"l1": "科技", "l2": "AI", "l3": "模型"}\n```\nDone.'
    })
    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = classify_with_ollama("title", "content")
    assert result == ("科技", "AI", "模型")


def test_classify_with_ollama_timeout_returns_none(monkeypatch):
    """urlopen 超时 → None。"""
    monkeypatch.setenv("OLLAMA_CLASSIFY_TIMEOUT", "5")
    import socket
    with patch("urllib.request.urlopen", side_effect=socket.timeout("timed out")):
        result = classify_with_ollama("title", "content")
    assert result is None


def test_classify_with_ollama_http_error_returns_none(monkeypatch):
    """HTTP 500 → None。"""
    monkeypatch.setenv("OLLAMA_CLASSIFY_TIMEOUT", "5")
    from urllib.error import HTTPError
    with patch("urllib.request.urlopen",
               side_effect=HTTPError("http://x", 500, "Server Error", {}, None)):
        result = classify_with_ollama("title", "content")
    assert result is None


def test_classify_with_ollama_unparseable_response_returns_none(monkeypatch):
    """模型返回无法解析的文本 → None。"""
    monkeypatch.setenv("OLLAMA_CLASSIFY_TIMEOUT", "5")
    mock_resp = _mock_urlopen_response({
        "response": "I cannot help with that."
    })
    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = classify_with_ollama("title", "content")
    assert result is None


def test_classify_with_ollama_connection_error_returns_none(monkeypatch):
    """连接被拒（Ollama 未启动） → None。"""
    monkeypatch.setenv("OLLAMA_URL", "http://localhost:99999")
    monkeypatch.setenv("OLLAMA_CLASSIFY_TIMEOUT", "1")
    result = classify_with_ollama("title", "content")
    assert result is None


def test_classify_with_ollama_uses_env_vars(monkeypatch):
    """环境变量 OLLAMA_MODEL / OLLAMA_URL 被读取。"""
    monkeypatch.setenv("OLLAMA_MODEL", "custom-model:7b")
    monkeypatch.setenv("OLLAMA_URL", "http://custom-host:8080")
    monkeypatch.setenv("OLLAMA_CLASSIFY_TIMEOUT", "5")

    captured = {}

    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self):
            return json.dumps({"response": '{"l1": "x", "l2": "y", "l3": "z"}'}).encode("utf-8")

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["data"] = json.loads(req.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResp()

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        classify_with_ollama("title", "content")

    assert captured["url"] == "http://custom-host:8080/api/generate"
    assert captured["data"]["model"] == "custom-model:7b"
    assert captured["timeout"] == 5.0


def test_classify_with_ollama_truncates_content(monkeypatch):
    """content 超过 3000 字符应被截断。"""
    monkeypatch.setenv("OLLAMA_CLASSIFY_TIMEOUT", "5")

    long_content = "x" * 5000

    captured = {}

    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self):
            return json.dumps({"response": '{"l1": "a", "l2": "b", "l3": "c"}'}).encode("utf-8")

    def fake_urlopen(req, timeout=None):
        payload = json.loads(req.data.decode("utf-8"))
        captured["prompt"] = payload["prompt"]
        return FakeResp()

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        classify_with_ollama("title", long_content)

    # Prompt should contain at most 3000 chars of content
    assert long_content not in captured["prompt"]
    assert "x" * 3000 in captured["prompt"] or "x" * 2999 in captured["prompt"]
