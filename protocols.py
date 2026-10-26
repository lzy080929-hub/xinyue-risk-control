"""Frozen application protocols; old drafts keep their original conditions."""
from __future__ import annotations

EXPERIMENT_V4 = "xinyue-fixedrate-v4"
CONSENT_V4 = "consent-fixedrate-v4"
FORM_V4 = "bank-eight-page-v2"
BEHAVIOR_V4 = "behavior-pledge-v3"
UI_V4 = "bank-application-v2"
PLEDGE_VERSION = "pledge-v1"
PLEDGE_TEXT = "本人已阅读本次申请说明和展示条款，确认以上信息为本人自主填写。"
RRT_VERSION = "rrt-uq50-v1"
RRT_QUESTION = "过去12个月，你是否曾在约定还款日（含事先约定的宽限期）结束后，仍未付清个人信用借款当期必须偿还的金额？"


def assigned_terms() -> dict:
    # This is an explicit teaching scenario, never inferred from income or behavior.
    return {"scenario_version": "fixed-6-annuity-v1", "interest_rate": 6.0,
        "rate_assignment_method": "fixed_scenario", "rate_basis": "nominal_annual",
        "repayment_method": "monthly_annuity", "additional_fees": 0,
        "pledge_version": PLEDGE_VERSION}
