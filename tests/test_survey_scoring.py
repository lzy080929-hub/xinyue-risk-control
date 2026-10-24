from __future__ import annotations

import pytest

from survey import (
    ITEM_COUNT,
    REVERSE_ITEM_NUMBERS,
    SURVEY_ITEMS,
    score_survey,
)


def test_questionnaire_bank_is_fixed_at_29_items():
    assert ITEM_COUNT == 29
    assert len(SURVEY_ITEMS) == 29
    assert REVERSE_ITEM_NUMBERS == {7, 8, 15, 16, 23, 24, 29}
    assert SURVEY_ITEMS[6].startswith("逾期还款对我没有太大影响")
    assert SURVEY_ITEMS[28].startswith("我担心自己可能无法完全按时还清")


def test_all_fours_gives_mean_four_for_every_subscale():
    result = score_survey({number: 4 for number in range(1, 30)})
    assert set(result["subscales"]) == {"ATR", "SN", "PBC", "LRI"}
    for summary in result["subscales"].values():
        assert summary["total"] == summary["expected_count"] * 4
        assert summary["mean"] == 4
        assert summary["valid_count"] == summary["expected_count"]
    assert result["all_29_compatibility"]["mean"] == 4


def test_positive_seven_and_reverse_one_gives_mean_seven_everywhere():
    answers = {
        number: 1 if number in REVERSE_ITEM_NUMBERS else 7
        for number in range(1, 30)
    }
    result = score_survey(answers)
    for summary in result["subscales"].values():
        assert summary["mean"] == 7
        assert 1 <= summary["mean"] <= 7
    assert result["all_29_compatibility"]["mean"] == 7
    for number in REVERSE_ITEM_NUMBERS:
        assert result["items"][number]["scored"] == 7


def test_missing_values_stay_null_and_are_not_counted_as_zero():
    # Every answered item scores 5 after the reverse conversion, so a zero
    # substitution for the two missing items would make the mean less than 5.
    answers = {
        number: 3 if number in REVERSE_ITEM_NUMBERS else 5
        for number in range(1, 30)
    }
    answers[1] = None
    answers[7] = None
    result = score_survey(answers)

    assert result["items"][1]["raw"] is None
    assert result["items"][1]["scored"] is None
    assert result["items"][7]["raw"] is None
    assert result["items"][7]["scored"] is None
    assert result["subscales"]["ATR"]["valid_count"] == 6
    assert result["subscales"]["ATR"]["total"] == 30
    assert result["subscales"]["ATR"]["mean"] == 5
    assert result["subscales"]["ATR"]["missing_item_numbers"] == [1, 7]
    assert result["all_29_compatibility"]["valid_count"] == 27


def test_missing_item_numbers_are_global_across_subscales():
    answers = {number: 4 for number in range(1, 30)}
    answers[9] = None
    answers[17] = None
    answers[29] = None
    result = score_survey(answers)
    assert result["subscales"]["SN"]["missing_item_numbers"] == [9]
    assert result["subscales"]["PBC"]["missing_item_numbers"] == [17]
    assert result["subscales"]["LRI"]["missing_item_numbers"] == [29]
    assert result["all_29_compatibility"]["missing_item_numbers"] == [9, 17, 29]


def test_all_missing_has_no_fabricated_zero_mean():
    result = score_survey({})
    assert result["subscales"]["ATR"]["total"] is None
    assert result["subscales"]["ATR"]["mean"] is None
    assert result["subscales"]["ATR"]["valid_count"] == 0
    assert result["all_29_compatibility"]["mean"] is None


def test_scores_are_within_likert_range_and_raw_answers_are_retained():
    answers = {
        number: ((number * 3) % 7) + 1
        for number in range(1, 30)
    }
    result = score_survey(answers)
    for number, value in answers.items():
        assert result["items"][number]["raw"] == value
        assert 1 <= result["items"][number]["scored"] <= 7
        assert result["items"][number]["scored"] == (
            8 - value if number in REVERSE_ITEM_NUMBERS else value
        )
    for summary in result["subscales"].values():
        assert 1 <= summary["mean"] <= 7


@pytest.mark.parametrize("invalid", [0, 8, "5", True, 4.5])
def test_invalid_answers_are_rejected(invalid):
    answers = {number: 4 for number in range(1, 30)}
    answers[2] = invalid
    with pytest.raises(ValueError):
        score_survey(answers)


def test_unknown_item_number_is_rejected():
    answers = {number: 4 for number in range(1, 30)}
    answers[30] = 4
    with pytest.raises(ValueError):
        score_survey(answers)
