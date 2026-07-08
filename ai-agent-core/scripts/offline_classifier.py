"""Phase 7: External LLM classifier — offline small-model classification gateway.

Integrates with Ollama local models (Qwen 3b / Llama 3.2 3b) as a
fallback / auxiliary classifier for the knowledge ingestion pipeline.

Usage:
    # As standalone script
    python -m scripts.offline_classifier --path rag/corpus/foo.md

    # As module
    from scripts.offline_classifier import classify_with_ollama

Environment:
    OLLAMA_URL:        Ollama API base URL (default http://localhost:11434)
    OLLAMA_MODEL:      Model name (default "qwen2.5:3b")
    OLLAMA_CLASSIFY_TIMEOUT:  Request timeout in seconds (default 30)
    OLLAMA_CLASSIFY_ENABLED:  1/true/yes — enable for pipeline (default 0)

The classifier sends title + first 3000 chars to Ollama and expects a
JSON response: {"l1": "科技", "l2": "AI", "l3": "模型"}
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

_PROMPT_TEMPLATE = """你是一个知识图谱分类器。根据文档标题和前几段内容，返回最合适的 L1/L2/L3 三级分类。

可用的 L1 分类：{{l1_tags}}
L1-L2-L3 映射：{{tag_map}}

文档标题：{{title}}
文档开头：{{content}}

请严格按照以下 JSON 格式回复（不要任何其他文字）：
{"l1": "一级分类", "l2": "二级分类", "l3": "三级分类"}
如果无法判断，返回：{"l1": "未分类", "l2": "Misc", "l3": "General"}"""


def _load_tag_rules(path: str | None = None) -> dict[str, Any]:
    """Load tag_rules.yaml to extract L1 tags and mapping."""
    try:
        import yaml
    except ImportError:
        return {"l1_tags": [], "tag_map": ""}

    if path is None:
        path = str(Path(__file__).resolve().parent.parent / "config" / "tag_rules.yaml")

    try:
        with open(path, "r", encoding="utf-8") as f:
            rules = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return {"l1_tags": [], "tag_map": ""}

    l1_tags = list(set(r.get("l1", "") for r in rules.get("rules", []) if r.get("l1")))
    if "defaults" in rules and rules["defaults"].get("l1"):
        l1_tags.append(rules["defaults"]["l1"])

    # Build a compact L1→L2 mapping
    l1_to_l2: dict[str, set[str]] = {}
    for r in rules.get("rules", []):
        l1 = r.get("l1", "")
        l2 = r.get("l2", "")
        if l1 and l2:
            l1_to_l2.setdefault(l1, set()).add(l2)

    tag_map_lines = []
    for l1, l2_set in sorted(l1_to_l2.items()):
        tag_map_lines.append(f"  {l1} → {', '.join(sorted(l2_set))}")
    tag_map = "\n".join(tag_map_lines) if tag_map_lines else ""

    return {"l1_tags": sorted(set(l1_tags)), "tag_map": tag_map}


def classify_with_ollama(
    title: str,
    content: str,
    model: str | None = None,
    base_url: str | None = None,
    timeout: float | None = None,
) -> tuple[str, str, str] | None:
    """Call Ollama for L1/L2/L3 classification.

    Returns (l1, l2, l3) on success, or None on failure (timeout / parse error).
    """
    model = model or os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
    base_url = base_url or os.environ.get("OLLAMA_URL", "http://localhost:11434")
    timeout = timeout or float(os.environ.get("OLLAMA_CLASSIFY_TIMEOUT", "30"))

    tags = _load_tag_rules()
    prompt = (
        _PROMPT_TEMPLATE
        .replace("{{l1_tags}}", ", ".join(tags["l1_tags"]) if tags["l1_tags"] else "科技, 政经, 文史, 生活, 项目")
        .replace("{{tag_map}}", tags["tag_map"] or "（请自行推断）")
        .replace("{{title}}", title or "（无标题）")
        .replace("{{content}}", content[:3000])
    )

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1},
    }

    try:
        import urllib.request
        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        start = time.monotonic()
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
        elapsed = time.monotonic() - start
        data = json.loads(body)
        raw = data.get("response", "")
    except Exception as e:
        print(f"[offline_classifier] Ollama call failed: {type(e).__name__}: {e}", file=sys.stderr)
        return None

    # Parse JSON response from model output
    try:
        # Try to extract JSON from response (models may add extra text)
        import re
        json_match = re.search(r'\{[^{}]*"l1"[^{}]*\}', raw, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group(0))
        else:
            parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        print(f"[offline_classifier] unparseable response: {raw[:200]}", file=sys.stderr)
        return None

    l1 = parsed.get("l1", "未分类")
    l2 = parsed.get("l2", "Misc")
    l3 = parsed.get("l3", "General")

    print(
        f"[offline_classifier] {title[:40]:40s} → {l1}/{l2}/{l3} "
        f"(model={model}, {elapsed:.1f}s)",
        file=sys.stderr,
    )
    return (l1, l2, l3)


def classify_hook(
    title: str,
    content: str,
    rules_result: tuple[str, str, str],
) -> tuple[str, str, str]:
    """External classifier hook for pipeline_worker.

    If offline LLM is enabled and returns a non-default result, use it.
    Otherwise fall back to rules_result.

    This is the integration point: called from pipeline_worker.classify_multi()
    as an optional refinement pass.
    """
    enabled = os.environ.get("OLLAMA_CLASSIFY_ENABLED", "0").lower() in ("1", "true", "yes")
    if not enabled:
        return rules_result

    ollama_result = classify_with_ollama(title, content)
    if ollama_result is None:
        return rules_result

    ollama_l1, ollama_l2, ollama_l3 = ollama_result
    # If Ollama returned a default (unclassified), trust rules instead
    if ollama_l1 in ("未分类", "") or ollama_l2 == "Misc":
        return rules_result

    return ollama_result


# ------------------------------------------------------------------
# CLI — standalone test
# ------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Offline LLM classifier for .md corpus")
    parser.add_argument("--path", required=True, help="Path to markdown file")
    parser.add_argument("--model", default=None, help="Ollama model name (default qwen2.5:3b)")
    parser.add_argument("--url", default=None, help="Ollama API base URL")
    args = parser.parse_args()

    path = Path(args.path)
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        return 1

    raw = path.read_text(encoding="utf-8")
    import re as _re
    title_match = _re.search(r"^#\s+(.+)$", raw, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else ""

    result = classify_with_ollama(title, raw, model=args.model, base_url=args.url)
    if result is None:
        print("Classification failed", file=sys.stderr)
        return 1
    print(json.dumps({"l1": result[0], "l2": result[1], "l3": result[2]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())