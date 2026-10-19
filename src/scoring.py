"""Rules-based triage scoring for inbound partner opportunities."""

import math

STRATEGIC_TYPES = {"AI model provider", "AI agent platform", "Cloud infrastructure", "Data platform"}
ADJACENT_TYPES = {"Cybersecurity", "Healthcare software", "Financial software",
                  "Industrial software", "Telecommunications"}
SOURCE_POINTS = {"Referral": 15, "Event": 10, "Inbound form": 5}
REQUIRED_FIELDS = ["company", "partner_type", "region", "employees", "est_annual_value_usd", "source"]


def is_missing(value) -> bool:
    """True if a field is empty, None, or NaN (how pandas marks blank CSV cells)."""
    return value is None or value == "" or (isinstance(value, float) and math.isnan(value))


def score_value(value) -> int:
    if is_missing(value):
        return 0
    value = float(value)
    if value >= 500_000:
        return 30
    if value >= 200_000:
        return 20
    if value >= 50_000:
        return 10
    return 0


def score_partner_type(partner_type) -> int:
    if partner_type in STRATEGIC_TYPES:
        return 25
    if partner_type in ADJACENT_TYPES:
        return 15
    return 5


def score_size(employees) -> int:
    if is_missing(employees):
        return 0
    employees = int(employees)
    if employees >= 1000:
        return 20
    if employees >= 200:
        return 12
    if employees >= 50:
        return 5
    return 0


def assign_tier(score: int) -> str:
    if score >= 65:
        return "Priority"
    if score >= 35:
        return "Nurture"
    return "Deprioritize"


def score_opportunity(opp: dict) -> dict:
    """Score one opportunity and return the total, tier, point breakdown, and missing fields."""
    breakdown = {
        "deal_value": score_value(opp.get("est_annual_value_usd")),
        "partner_type": score_partner_type(opp.get("partner_type")),
        "company_size": score_size(opp.get("employees")),
        "source": SOURCE_POINTS.get(opp.get("source"), 0),
    }
    total = sum(breakdown.values())
    missing = [f for f in REQUIRED_FIELDS if is_missing(opp.get(f))]
    return {
        "opportunity_id": opp.get("opportunity_id"),
        "company": opp.get("company"),
        "score": total,
        "tier": assign_tier(total),
        "breakdown": breakdown,
        "missing_fields": missing,
    }
