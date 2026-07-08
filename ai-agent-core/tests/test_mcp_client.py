from mcp.mcp_client import MCPClient


class _FakeTool:
    def __init__(self, name: str):
        self.name = name

    def execute(self, args: dict) -> dict:
        return {"ok": True, "result": f"{self.name}:{args.get('q')}", "error": None}


def test_register_and_list():
    client = MCPClient()
    client.register("kb", _FakeTool("kb"))
    assert client.list_tools() == ["kb"]


def test_call_returns_envelope():
    client = MCPClient()
    client.register("kb", _FakeTool("kb"))
    out = client.call("kb", {"q": "hello"})
    assert out["ok"] is True
    assert out["result"] == "kb:hello"


def test_call_unknown_tool_returns_error():
    client = MCPClient()
    out = client.call("nope", {})
    assert out["ok"] is False
    assert "unknown tool" in out["error"].lower()


def test_register_duplicate_overwrites():
    client = MCPClient()
    client.register("kb", _FakeTool("v1"))
    client.register("kb", _FakeTool("v2"))
    out = client.call("kb", {"q": "x"})
    assert out["result"] == "v2:x"
