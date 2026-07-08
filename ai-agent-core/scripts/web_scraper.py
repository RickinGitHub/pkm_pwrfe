"""URL → Markdown ingestion entrypoint.

Reuses skills.fetch_web_to_md for HTTP + HTML→MD conversion.
Drops output into rag/corpus/ (default), where background_worker.py
picks it up automatically.

CLI:
    python -m scripts.web_scraper <url> [--format md] [--save-img] [--save-attachments] [--sync]

--save-img:         download article images to rag/corpus/images/ and rewrite
                    .md URLs to local relative paths (recommended for WeChat,
                    prevents CDN rot from breaking image links).
--save-attachments: download file attachments (pdf/zip/docx/mp4/mp3/...) to
                    rag/corpus/attachments/ and rewrite .md URLs.
--sync:             also run pipeline_worker.process_file() immediately (useful
                    when the watcher is not running, e.g. in tests).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure project root on sys.path when invoked via `python -m scripts.web_scraper`.
_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from skills.fetch_web_to_md import FetchWebToMd  # noqa: E402


def fetch_to_corpus(
    url: str,
    fmt: str = "md",
    timeout: int = 30,
    save_img: bool = False,
    save_attachments: bool = False,
) -> dict:
    """Fetch URL and save into rag/corpus/. Returns FetchWebToMd envelope."""
    skill = FetchWebToMd()
    return skill.execute({
        "op": "fetch",
        "url": url,
        "format": fmt,
        "timeout": timeout,
        "save_img": save_img,
        "save_attachments": save_attachments,
    })


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch URL → Markdown into rag/corpus/")
    parser.add_argument("url", help="http(s):// URL to scrape")
    parser.add_argument("--format", default="md", choices=["md", "json", "html"])
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument(
        "--save-img",
        action="store_true",
        help="Download article images to rag/corpus/images/ (recommended for WeChat)",
    )
    parser.add_argument(
        "--save-attachments",
        action="store_true",
        help="Download file attachments (pdf/zip/docx/mp4/...) to rag/corpus/attachments/",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Run pipeline_worker.process_file() immediately after fetch",
    )
    args = parser.parse_args()

    out = fetch_to_corpus(
        args.url,
        fmt=args.format,
        timeout=args.timeout,
        save_img=args.save_img,
        save_attachments=args.save_attachments,
    )
    if not out["ok"]:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 1

    if args.sync:
        from scripts.pipeline_worker import process_file
        filepath = out["result"]["filepath"]
        proc = process_file(Path(filepath))
        out["result"]["pipeline"] = proc

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
