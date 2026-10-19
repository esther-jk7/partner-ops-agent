import pandas as pd
from src.scoring import assign_tier, score_opportunity


def test_tier_boundaries():
    assert assign_tier(65) == "Priority"
    assert assign_tier(64) == "Nurture"
    assert assign_tier(35) == "Nurture"
    assert assign_tier(34) == "Deprioritize"


def test_perfect_opportunity_scores_max():
    opp = {"company": "Test Co", "partner_type": "AI model provider", "region": "Europe",
           "employees": 5000, "est_annual_value_usd": 1_000_000, "source": "Referral"}
    result = score_opportunity(opp)
    assert result["score"] == 90
    assert result["tier"] == "Priority"
    assert result["missing_fields"] == []


def test_missing_value_scores_zero_and_is_flagged():
    opp = {"company": "Test Co", "partner_type": "Retail software", "region": "Europe",
           "employees": 100, "est_annual_value_usd": float("nan"), "source": "Inbound form"}
    result = score_opportunity(opp)
    assert result["breakdown"]["deal_value"] == 0
    assert "est_annual_value_usd" in result["missing_fields"]


def test_sample_data_tier_distribution():
    df = pd.read_csv("data/inbound_opportunities.csv")
    tiers = [score_opportunity(o)["tier"] for o in df.to_dict("records")]
    assert tiers.count("Priority") == 3
    assert tiers.count("Nurture") == 6
    assert tiers.count("Deprioritize") == 3
