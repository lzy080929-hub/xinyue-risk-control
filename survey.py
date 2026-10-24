"""The fixed 29-item repayment questionnaire and its scoring definition.

The item bank is versioned and must not be silently reordered or reworded.
Scoring runs only on the server; missing answers stay missing and are never
converted to zero.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SCALE_VERSION = "repayment-29-v1"
SCORING_VERSION = "repayment-29-scoring-v1"
LIKERT_MIN = 1
LIKERT_MAX = 7

SURVEY_ITEMS: tuple[str, ...] = (
    "我认为按时还款是明智的选择",
    "即使还款压力较大，我仍会优先保证按时还款",
    "我认为按时还款是应该履行的责任",
    "还款让我感到安心和踏实",
    "积极还款对我的未来发展有益",
    "如果暂时资金紧张，我会选择最低还款额而不是逾期",
    "逾期还款对我没有太大影响",
    "如果只是因为忘记还款而延迟几天，我不会太自责",
    "我的家人认为我应该按时还款",
    "我的朋友认为按时还款很重要",
    "金融机构/贷款机构期望我按时还款",
    "我愿意遵从家人对我还款的期望",
    "社会舆论支持年轻人按时偿还贷款",
    "大多数我尊重的人都认为我应该按时还款",
    "我身边的人并不特别关注我的还款记录",
    "他人对我的还款行为有一定期望，但影响不大",
    "我有能力按时偿还贷款",
    "我可以自主决定还款的时间和金额",
    "我有足够的收入/经济来源来还款",
    "如果遇到困难，我知道如何寻求帮助",
    "按时还款在我力所能及的范围内",
    "我有信心能够应对还款过程中可能出现的挑战",
    "遇到突发经济困难时，按时还款对我来说比较困难",
    "有时外部因素会影响我按时还款的能力",
    "我打算在未来按时偿还我的贷款",
    "我会努力确保按时还款",
    "我计划按时偿还所有贷款",
    "我愿意为按时还款付出必要的努力",
    "我担心自己可能无法完全按时还清所有贷款",
)

REVERSE_ITEM_NUMBERS = frozenset({7, 8, 15, 16, 23, 24, 29})

SUBSCALES: dict[str, tuple[int, ...]] = {
    "ATR": tuple(range(1, 9)),
    "SN": tuple(range(9, 17)),
    "PBC": tuple(range(17, 25)),
    "LRI": tuple(range(25, 30)),
}

SUBSCALE_LABELS = {
    "ATR": "还款态度（ATR）",
    "SN": "主观规范（SN）",
    "PBC": "感知行为控制（PBC）",
    "LRI": "还款意愿（LRI）",
}

LIKERT_LABELS = {
    1: "非常不同意",
    2: "不同意",
    3: "有点不同意",
    4: "中立",
    5: "有点同意",
    6: "同意",
    7: "非常同意",
}

ITEM_COUNT = len(SURVEY_ITEMS)


def _validated_raw(value: Any, item_number: int) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"第 {item_number} 题必须是 1—7 的整数或缺失值")
    if value < LIKERT_MIN or value > LIKERT_MAX:
        raise ValueError(f"第 {item_number} 题超出 1—7 范围")
    return value


def _total_and_mean(
    values: list[int | None], item_numbers: tuple[int, ...]
) -> dict[str, int | float | None]:
    if len(values) != len(item_numbers):
        raise ValueError("计分项数与题号数量不一致")
    valid = [value for value in values if value is not None]
    total = sum(valid) if valid else None
    mean = round(total / len(valid), 4) if valid and total is not None else None
    return {
        "total": total,
        "mean": mean,
        "valid_count": len(valid),
        "expected_count": len(values),
        "missing_item_numbers": [
            number
            for number, value in zip(item_numbers, values, strict=True)
            if value is None
        ],
    }


def score_survey(raw_answers: Mapping[int, int | None]) -> dict[str, Any]:
    """Score the questionnaire server-side while retaining every raw answer.

    Missing answers remain null and are excluded from totals and means. They are
    never converted to zero. The 29-item total is exposed only as a labelled
    compatibility field, not as a measure of true repayment willingness.
    """
    unknown = set(raw_answers) - set(range(1, ITEM_COUNT + 1))
    if unknown:
        raise ValueError(f"存在未知题号：{sorted(unknown)}")

    items: dict[int, dict[str, Any]] = {}
    scored_values: list[int | None] = []

    for item_number in range(1, ITEM_COUNT + 1):
        raw = _validated_raw(raw_answers.get(item_number), item_number)
        is_reverse = item_number in REVERSE_ITEM_NUMBERS
        scored = None if raw is None else (8 - raw if is_reverse else raw)
        items[item_number] = {
            "raw": raw,
            "scored": scored,
            "reverse": is_reverse,
        }
        scored_values.append(scored)

    subscales: dict[str, dict[str, Any]] = {}
    for name, item_numbers in SUBSCALES.items():
        values = [scored_values[number - 1] for number in item_numbers]
        summary = _total_and_mean(values, item_numbers)
        summary["label"] = SUBSCALE_LABELS[name]
        summary["item_numbers"] = list(item_numbers)
        subscales[name] = summary

    compatibility = _total_and_mean(
        scored_values, tuple(range(1, ITEM_COUNT + 1))
    )
    return {
        "scale_version": SCALE_VERSION,
        "scoring_version": SCORING_VERSION,
        "items": items,
        "subscales": subscales,
        "all_29_compatibility": compatibility,
        "notes": {
            "reverse_conversion": "8 - raw",
            "missing_handling": "null; excluded from totals and means; never zero",
            "lri_is_willingness_scale": True,
        },
    }
