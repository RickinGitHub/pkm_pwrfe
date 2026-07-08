from pathlib import Path
import textwrap
from config.loader import load_rules, load_routing


def test_load_rules_parses_required_fields(tmp_path: Path):
    p = tmp_path / "rules.yaml"
    p.write_text(textwrap.dedent("""
        role: "Senior AI Infrastructure Engineer"
        max_output_tokens: 1024
        prompt_prefix: "Think step-by-step but output final result as JSON."
        output_format: "json"
    """))
    rules = load_rules(str(p))
    assert rules.role.startswith("Senior AI")
    assert rules.max_output_tokens == 1024
    assert rules.output_format == "json"


def test_load_rules_rejects_invalid_output_format(tmp_path: Path):
    p = tmp_path / "rules.yaml"
    p.write_text("role: x\nmax_output_tokens: 1\nprompt_prefix: x\noutput_format: yaml\n")
    try:
        load_rules(str(p))
    except ValueError:
        return
    raise AssertionError("expected ValueError for invalid output_format")


def test_load_routing_parses_entries(tmp_path: Path):
    p = tmp_path / "routing.yaml"
    p.write_text(textwrap.dedent("""
        entries:
          - intent: "math.*"
            tool_type: "skill"
            tool_name: "math_logic"
            fallback: "llm"
          - intent: "file.read"
            tool_type: "skill"
            tool_name: "file_ops"
            fallback: null
    """))
    routing = load_routing(str(p))
    assert len(routing.entries) == 2
    assert routing.entries[0].intent == "math.*"
    assert routing.entries[0].fallback == "llm"
    assert routing.entries[1].fallback is None


def test_load_routing_missing_file_raises(tmp_path: Path):
    try:
        load_routing(str(tmp_path / "nope.yaml"))
    except FileNotFoundError:
        return
    raise AssertionError("expected FileNotFoundError")
