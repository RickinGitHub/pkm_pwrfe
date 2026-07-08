import ast
import operator
from typing import Union

from .base import ok, err


_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _safe_eval(node: ast.AST) -> Union[int, float]:
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise ValueError(f"invalid constant: {node.value!r}")
    if isinstance(node, ast.BinOp):
        fn = _BIN_OPS.get(type(node.op))
        if fn is None:
            raise ValueError(f"unsupported operator: {type(node.op).__name__}")
        return fn(_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp):
        fn = _UNARY_OPS.get(type(node.op))
        if fn is None:
            raise ValueError(f"unsupported unary: {type(node.op).__name__}")
        return fn(_safe_eval(node.operand))
    raise ValueError(f"invalid expression node: {type(node).__name__}")


class MathLogic:
    def execute(self, args: dict) -> dict:
        op = args.get("op")
        if op == "calc":
            expr = args.get("expr")
            if not isinstance(expr, str):
                return err("missing or invalid 'expr'")
            try:
                tree = ast.parse(expr, mode="eval")
            except SyntaxError as e:
                return err(f"invalid expression: {e}")
            try:
                return ok(_safe_eval(tree))
            except ValueError as e:
                return err(f"invalid expression: {e}")
        if op == "stats":
            values = args.get("values")
            if not isinstance(values, list) or not values:
                return err("missing or empty 'values'")
            try:
                nums = [float(v) for v in values]
            except (TypeError, ValueError) as e:
                return err(f"invalid value in 'values': {e}")
            return ok({
                "mean": sum(nums) / len(nums),
                "sum": sum(nums),
                "count": len(nums),
            })
        return err(f"unknown op: {op}")
