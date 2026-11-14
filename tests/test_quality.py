"""Answer parsing and match-rate math for the quality checks."""

from icr.quality import checks


def test_gold_answer_strips_the_marker_and_commas():
    assert checks.gold_answer({"answer": "She has 5.\n#### 1,250"}) == "1250"


def test_parse_answer_prefers_the_tagged_line():
    text = "First 3 + 4 = 7. Then 7 * 2 = 14.\nAnswer: 14"
    assert checks.parse_answer(text) == "14"
    assert checks.parse_answer("Answer: $1,250.50") == "1250.50"
    assert checks.parse_answer("Answer: 3\nWait.\nAnswer: 5") == "5"


def test_parse_answer_falls_back_to_the_last_number():
    assert checks.parse_answer("So the total is 42 apples.") == "42"
    assert checks.parse_answer("I cannot solve this.") is None


def test_is_correct_compares_numbers_not_strings():
    assert checks.is_correct("18.0", "18")
    assert not checks.is_correct("17", "18")
    assert not checks.is_correct(None, "18")


def test_match_rate_reports_exact_and_partial_agreement():
    a = ["same text", "abcdefgh", "xyz"]
    b = ["same text", "abcdxxxx", "xyz"]
    rate = checks.match_rate(a, b)
    assert rate["exact_match"] == round(2 / 3, 4)
    assert rate["mean_common_prefix"] == round((1 + 0.5 + 1) / 3, 4)
