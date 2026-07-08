from pathlib import Path

from .base import ok, err


class FileOps:
    def execute(self, args: dict) -> dict:
        op = args.get("op")
        path = args.get("path")
        if not op:
            return err("missing 'op'")
        if not path:
            return err("missing 'path'")
        p = Path(path)
        if op == "read":
            if not p.exists():
                return err(f"no such file: {path}")
            return ok(p.read_text(encoding="utf-8"))
        if op == "clean":
            if not p.exists():
                return err(f"no such file: {path}")
            lines = p.read_text(encoding="utf-8").splitlines()
            cleaned = [ln.strip() for ln in lines if ln.strip()]
            return ok("\n".join(cleaned))
        return err(f"unknown op: {op}")
