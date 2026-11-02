import pandas as pd

from src.scoring import CLOSE_CALL_BAND, assign_tier, review_flags, score_opportunity

PERFECT = {"company": "Test Co", "partner_type": "AI model provider", "region": "Europe",
           "employees": 5000, "est_annual_value_usd": 1_000_000, "source": "Referral",
           "partnership_model": "Platform distribution", "revenue_model": "Licensing",
           "integration_effort": "Low", "wants_model_training": "No"}


def test_tier_boundaries():
    assert assign_tier(70) == "Priority"
    assert assign_tier(69) == "Nurture"
    assert assign_tier(40) == "Nurture"
    assert assign_tier(39) == "Deprioritize"


def test_perfect_opportunity_scores_max_with_no_flags():
    result = score_opportunity(PERFECT)
    assert result["score"] == 100
    assert result["tier"] == "Priority"
    assert result["missing_fields"] == []
    assert result["needs_review"] is False
    assert result["route_to_sales"] is False


def test_every_point_has_a_reason():
    result = score_opportunity(PERFECT)
    assert len(result["reasons"]) == len(result["breakdown"])
    for (name, points), reason in zip(result["breakdown"].items(), result["reasons"]):
        assert reason.startswith(f"+{points} "), f"{name}: reason does not match points"


def test_data_rights_gate_flags_even_a_perfect_score():
    result = score_opportunity({**PERFECT, "wants_model_training": "Yes"})
    assert result["tier"] == "Priority"
    assert result["needs_review"] is True
    assert result["review_reasons"][0].startswith("Data rights")


def test_close_call_band_edges():
    low, high = CLOSE_CALL_BAND
    assert any(r.startswith("Close call") for r in review_flags(PERFECT, low))
    assert any(r.startswith("Close call") for r in review_flags(PERFECT, high))
    assert review_flags(PERFECT, high + 1) == []
    assert review_flags(PERFECT, low - 1) == []


def test_missing_value_scores_zero_and_triggers_review():
    result = score_opportunity({**PERFECT, "est_annual_value_usd": float("nan")})
    assert result["breakdown"]["deal_value"] == 0
    assert "est_annual_value_usd" in result["missing_fields"]
    assert any(r.startswith("Missing scoring inputs") for r in result["review_reasons"])


def test_client_request_routes_to_sales():
    result = score_opportunity({**PERFECT, "partnership_model": "Client request",
                                "revenue_model": "Client purchase"})
    assert result["route_to_sales"] is True
    assert result["breakdown"]["partnership_model"] == 0


def test_unknown_data_rights_counts_as_missing():
    result = score_opportunity({**PERFECT, "wants_model_training": "Unknown"})
    assert "wants_model_training" in result["missing_fields"]


def test_sample_data_tier_distribution():
    """Calibration guardrail: if too many opportunities are Priority, the tier stops meaning anything.

    The threshold was raised from 60 to 65 after an early run flagged 58% as Priority.
    """
    df = pd.read_csv("data/inbound_opportunities.csv")
    tiers = [score_opportunity(o)["tier"] for o in df.to_dict("records")]
    priority_share = tiers.count("Priority") / len(tiers)
    assert 0.15 <= priority_share <= 0.40, f"Priority share {priority_share:.0%} is outside 15-40%"
    assert {"Priority", "Nurture", "Deprioritize"} <= set(tiers), "Every tier should appear in the sample"
