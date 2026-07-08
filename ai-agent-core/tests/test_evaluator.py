from harness.evaluator import Evaluator


def test_valid_json_result_passes():
    ev = Evaluator(expected_format="json")
    out = ev.validate({"ok": True, "result": {"x": 1}, "error": None})
    assert out["ok"] is True
    assert out["error"] is None


def test_invalid_envelope_returns_error():
    ev = Evaluator(expected_format="json")
    out = ev.validate({"foo": "bar"})
    assert out["ok"] is False
    assert "envelope" in out["error"].lower()


def test_json_format_accepts_non_json_string_as_text():
    ev = Evaluator(expected_format="json")
    out = ev.validate({"ok": True, "result": "not json", "error": None})
    assert out["ok"] is True
    assert out["result"] == "not json"


def test_json_format_accepts_parseable_string():
    ev = Evaluator(expected_format="json")
    out = ev.validate({"ok": True, "result": '{"x": 1}', "error": None})
    assert out["ok"] is True


def test_text_format_accepts_any_string():
    ev = Evaluator(expected_format="text")
    out = ev.validate({"ok": True, "result": "anything goes", "error": None})
    assert out["ok"] is True


def test_failed_skill_envelope_passes_through():
    ev = Evaluator(expected_format="json")
    out = ev.validate({"ok": False, "result": None, "error": "boom"})
    assert out["ok"] is False
    assert out["error"] == "boom"
