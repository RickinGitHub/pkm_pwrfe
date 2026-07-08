"""Tests for scripts.pipeline_worker.classify."""

from scripts.pipeline_worker import classify


_RULES = {
    "defaults": {"l1": "未分类", "l2": "Misc", "l3": "General"},
    "rules": [
        {"l1": "科技", "l2": "AI", "l3": "模型", "keywords": ["ai", "llm", "gpt"]},
        {"l1": "科技", "l2": "AI", "l3": "研发体系", "keywords": ["coding", "devops"]},
        {"l1": "职场", "l2": "成长", "l3": "策略", "keywords": ["职业", "简历"]},
    ],
}


def test_classify_matches_first_rule_by_keyword():
    l1, l2, l3 = classify("AI Coding 研发", "talks about llm and devops", _RULES)
    # First rule (模型) matches "ai"/"llm" first.
    assert (l1, l2, l3) == ("科技", "AI", "模型")


def test_classify_falls_through_to_second_rule_when_first_misses():
    l1, l2, l3 = classify("Coding 体系", "devops 流程", _RULES)
    assert (l1, l2, l3) == ("科技", "AI", "研发体系")


def test_classify_matches_chinese_keyword():
    l1, l2, l3 = classify("职业规划", "简历怎么写", _RULES)
    assert (l1, l2, l3) == ("职场", "成长", "策略")


def test_classify_returns_defaults_when_no_match():
    l1, l2, l3 = classify("hello", "world foo bar", _RULES)
    assert (l1, l2, l3) == ("未分类", "Misc", "General")


def test_classify_returns_defaults_for_empty_input():
    l1, l2, l3 = classify("", "", _RULES)
    assert (l1, l2, l3) == ("未分类", "Misc", "General")


def test_classify_uses_title_plus_first_5000_chars_of_content():
    # Keyword placed at char position 4990 should match; at 6000 should not.
    filler = "a" * 4990
    l1, l2, l3 = classify("doc", filler + " llm", _RULES)
    assert l1 == "科技"
    filler2 = "a" * 6000
    l1b, _, _ = classify("doc", filler2 + " llm", _RULES)
    assert l1b == "未分类"


def test_classify_case_insensitive():
    l1, l2, l3 = classify("AI AI AI", "LLM", _RULES)
    assert l1 == "科技"


def test_classify_empty_rules_dict_returns_hardcoded_defaults():
    l1, l2, l3 = classify("anything", "everything", {})
    assert l1 == "未分类"
    assert l2 == "Misc"
    assert l3 == "General"
