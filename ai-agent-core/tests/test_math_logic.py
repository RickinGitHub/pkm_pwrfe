from skills.math_logic import MathLogic


def test_calc_basic_arithmetic():
    out = MathLogic().execute({"op": "calc", "expr": "2 + 3 * 4"})
    assert out["ok"] is True
    assert out["result"] == 14


def test_calc_with_parens():
    out = MathLogic().execute({"op": "calc", "expr": "(2 + 3) * 4"})
    assert out["ok"] is True
    assert out["result"] == 20


def test_calc_rejects_letters():
    out = MathLogic().execute({"op": "calc", "expr": "__import__('os')"})
    assert out["ok"] is False
    assert "invalid" in out["error"].lower()


def test_stats_basic():
    out = MathLogic().execute({"op": "stats", "values": [1, 2, 3, 4]})
    assert out["ok"] is True
    assert out["result"]["mean"] == 2.5
    assert out["result"]["sum"] == 10
    assert out["result"]["count"] == 4


def test_stats_empty_returns_error():
    out = MathLogic().execute({"op": "stats", "values": []})
    assert out["ok"] is False
    assert "empty" in out["error"].lower()


def test_unknown_op():
    out = MathLogic().execute({"op": "magic"})
    assert out["ok"] is False
