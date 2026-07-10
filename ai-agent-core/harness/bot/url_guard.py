"""M8 — URL/SSRF guard + user authorization + path safety.

Design ref: docs/telegram_bot_design.md §6.2.1 / §6.2.2 / §6.2.4 / §6.2.6 / §6.2.7
Implementation plan: docs/telegram_bot_implementation_plan.md Phase 1.4
"""

from __future__ import annotations

import ipaddress
import os
import socket
from pathlib import Path
from urllib.parse import urlparse


_BLOCKED_NETS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def is_safe_url(url: str) -> bool:
    """拒绝指向内网/回环/元数据端点的 URL(DNS rebinding aware)。"""
    host = urlparse(url).hostname
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    if not infos:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except (ValueError, IndexError):
            continue
        if any(ip in net for net in _BLOCKED_NETS):
            return False
    return True


def is_authorized(user_id: int, raw: str | None = None) -> bool:
    """default-deny 白名单:空值拒绝所有人,`*` 显式公开,逗号分隔 ID 放行。"""
    raw = (raw if raw is not None else os.getenv("TELEGRAM_ALLOWED_USER_IDS", "")).strip()
    if raw == "*":
        return True
    if not raw:
        return False
    allowed = {int(x.strip()) for x in raw.split(",") if x.strip().isdigit()}
    return user_id in allowed


def safe_corpus_path(raw: str, corpus_root: str = "rag/corpus") -> Path | None:
    """规范化路径并校验落在 corpus_root 内,拒绝符号链接。"""
    root = Path(corpus_root).resolve()
    try:
        target = Path(raw).resolve()
    except (OSError, ValueError):
        return None
    try:
        target.relative_to(root)
    except ValueError:
        return None
    if target.is_symlink():
        return None
    return target


def sanitize_filename(original: str) -> str:
    """剥除任何路径前缀,只保留纯文件名。"""
    name = Path(original).name
    return name or "unnamed"
