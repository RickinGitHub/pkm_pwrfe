from typing import Protocol


class _Tool(Protocol):
    def execute(self, args: dict) -> dict: ...


class MCPClient:
    def __init__(self) -> None:
        self._tools: dict[str, _Tool] = {}

    def register(self, name: str, tool: _Tool) -> None:
        self._tools[name] = tool

    def list_tools(self) -> list[str]:
        return sorted(self._tools.keys())

    def call(self, name: str, args: dict) -> dict:
        tool = self._tools.get(name)
        if tool is None:
            return {"ok": False, "result": None, "error": f"unknown tool: {name}"}
        try:
            return tool.execute(args)
        except Exception as e:
            return {"ok": False, "result": None, "error": f"{type(e).__name__}: {e}"}
