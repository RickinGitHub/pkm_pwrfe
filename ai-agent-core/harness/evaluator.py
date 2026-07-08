import json
from typing import Any, Literal


_REQUIRED_KEYS = {"ok", "result", "error"}


class Evaluator:
    def __init__(self, expected_format: Literal["json", "text"] = "json"):
        self._format = expected_format

    def validate(self, output: dict) -> dict:
        if not isinstance(output, dict):
            return {"ok": False, "result": None, "error": "output must be a dict"}
        if not _REQUIRED_KEYS.issubset(output.keys()):
            missing = _REQUIRED_KEYS - set(output.keys())
            return {"ok": False, "result": None, "error": f"envelope missing keys: {missing}"}
        if not output["ok"]:
            return output
        result: Any = output["result"]
        if self._format == "json":
            if isinstance(result, (dict, list)):
                return output
            if isinstance(result, str):
                try:
                    json.loads(result)
                    return output
                except json.JSONDecodeError:
                    pass
            if isinstance(result, (int, float, bool)) or result is None:
                return output
            try:
                json.dumps(result)
                return output
            except (TypeError, ValueError) as e:
                return {"ok": False, "result": None, "error": f"result not json-serializable: {e}"}
        return output
