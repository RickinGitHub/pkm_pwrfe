from typing import Any, Protocol


class Skill(Protocol):
    def execute(self, args: dict) -> dict: ...


def ok(result: Any) -> dict:
    return {"ok": True, "result": result, "error": None}


def err(message: str) -> dict:
    return {"ok": False, "result": None, "error": message}
