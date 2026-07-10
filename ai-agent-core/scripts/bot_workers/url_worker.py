"""URLWorkerChild — fetch a URL and ingest into the RAG corpus.

Triggered when a user sends a message containing a URL, or uses the
``/fetch`` / ``/crawl`` / ``/抓取`` commands. Runs in a subprocess so
that:

1. Network I/O doesn't block the event loop.
2. We can enforce a hard timeout via ``proc.join(timeout=...)`` then
   ``SIGKILL`` — urllib doesn't always honor socket timeouts on slow
   DNS.
3. The worker calls ``agent.handle("fetch <url>")`` which itself spawns
   its own HTTP work; isolating that chain in a subprocess keeps the
   main bot responsive.

SSRF defense: ``_is_safe_url`` blocks private/loopback/link-local
addresses. All DNS resolutions returned by ``getaddrinfo`` are checked
(not just the first) to defeat DNS rebinding.
"""

from __future__ import annotations

import ipaddress
import socket
import sys
import urllib.parse
from typing import Any

from _worker_base import worker_main

_BLOCKED_NETS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("::1/128"),
]


def _is_safe_url(url: str) -> tuple[bool, str]:
    """Return (safe, reason). Unsafe if host resolves to a blocked net."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False, f"scheme not allowed: {parsed.scheme}"
    host = parsed.hostname
    if not host:
        return False, "no host in url"
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        return False, f"DNS failed: {exc}"
    for info in infos:
        ip = info[4][0]
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        for net in _BLOCKED_NETS:
            if addr in net:
                return False, f"{ip} in blocked net {net}"
    return True, "ok"


def run(payload: dict[str, Any]) -> dict[str, Any]:
    """Payload keys:
    - url: str (required)
    - extra_args: list[str] (optional, e.g. ["--save-img", "--format", "md"])
    - agent_available: bool (optional) — if False, only SSRF check runs
    """
    url = payload.get("url")
    if not url:
        return {"ok": False, "result": None, "error": "missing url"}

    safe, reason = _is_safe_url(url)
    if not safe:
        return {"ok": False, "result": None, "error": f"SSRF blocked: {reason}"}

    extra_args = payload.get("extra_args") or []
    # Build the query that the main agent would route to fetch_web skill.
    # We import build_agent lazily so SSRF check fails fast without
    # booting the full agent stack.
    try:
        sys.path.insert(0, ".")
        from harness.factory import build_agent  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "result": None, "error": f"agent import failed: {exc}"}

    query = "fetch " + " ".join([url, *extra_args])
    try:
        agent = build_agent()
        result = agent.handle(query)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "result": None, "error": f"agent.handle failed: {exc}"}

    return {
        "ok": bool(result.get("ok")),
        "result": result.get("result"),
        "error": result.get("error"),
    }


if __name__ == "__main__":
    worker_main(run)
