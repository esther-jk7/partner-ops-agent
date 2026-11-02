"""Rules-based qualification for inbound partner opportunities.

Every point comes with a plain-language reason, so a director can see and defend each score.
The weights are a starting assumption, to be calibrated with the partnerships team.
"""

import math

STRATEGIC_TYPES = {"AI model provider", "AI agent platform", "Cloud infrastructure", "Data platform"}
ADJACENT_TYPES = {"Cybersecurity", "Healthcare software", "Financial software",
                  "Industrial software", "Telecommunications"}

MODEL_POINTS = {
    "Platform distribution": (30, "embeds IDC intelligence in the partner's platform"),
    "Data alliance": (25, "combines partner data with IDC data"),
    "Content licensing": (15, "licenses or resells IDC content"),
    "Co-marketing": (10, "joint marketing only"),
    "Client request": (0, "a client request, not a partnership"),
}
REVENUE_POINTS = {
    "Licensing": (20, "recurring licensing revenue"),
    "Revenue share": (20, "recurring revenue share"),
    "Sponsorship": (10, "one-time sponsorship revenue"),
    "No revenue": (0, "no revenue to IDC"),
    "Client purchase": (0, "a client purchase, handled by sales"),
}
EFFORT_POINTS = {
    "Low": (10, "quick for a small team to launch"),
    "Medium": (5, "moderate setup"),
    "High": (0, "heavy setup"),
}
SOURCE_POINTS = {
    "Referral": (5, "warm introduction"),
    "Event": (3, "met in person"),
    "Inbound form": (1, "cold inbound"),
}

MAX_SCORE = 100
PRIORITY_THRESHOLD = 70
NURTURE_THRESHOLD = 40
CLOSE_CALL_BAND = (60, 69)

REQUIRED_FIELDS = ["company", "partner_type", "region", "employees", "est_annual_value_usd", "source",
                   "partnership_model", "revenue_model", "integration_effort", "wants_model_training"]
SCORING_INPUTS = {"partnership_model": "partnership model", "revenue_model": "revenue model",
                  "est_annual_value_usd": "deal value"}


def is_missing(value) -> bool:
    """True if a field is empty, None, or NaN (how pandas marks blank CSV cells)."""
    return value is None or value == "" or (isinstance(value, float) and math.isnan(value))


def is_unknown(field: str, value) -> bool:
    """Missing, or an explicit 'Unknown' answer to the data-rights question."""
    return is_missing(value) or (field == "wants_model_training" and value == "Unknown")


def _lookup(label: str, value, table: dict) -> tuple[int, str]:
    """Points and a reason for a field scored from a lookup table."""
    if is_missing(value):
        return 0, f"+0 {label}: not provided"
    points, why = table.get(value, (0, "unrecognized value"))
    return points, f"+{points} {label}: {value} ({why})"


def score_partner_type(partner_type) -> tuple[int, str]:
    if is_missing(partner_type):
        return 0, "+0 Partner type: not provided"
    if partner_type in STRATEGIC_TYPES:
        return 20, f"+20 Partner type: {partner_type} (strategic fit)"
    if partner_type in ADJACENT_TYPES:
        return 10, f"+10 Partner type: {partner_type} (adjacent fit)"
    return 5, f"+5 Partner type: {partner_type} (not a target type)"


def score_value(value) -> tuple[int, str]:
    if is_missing(value):
        return 0, "+0 Deal value: not provided"
    value = float(value)
    points = 15 if value >= 500_000 else 10 if value >= 200_000 else 5 if value >= 50_000 else 0
    return points, f"+{points} Deal value: ${value:,.0f} per year"


def assign_tier(score: int) -> str:
    if score >= PRIORITY_THRESHOLD:
        return "Priority"
    if score >= NURTURE_THRESHOLD:
        return "Nurture"
    return "Deprioritize"


def review_flags(opp: dict, total: int) -> list[str]:
    """Reasons a person must look at this opportunity, whatever its score."""
    reasons = []
    if opp.get("wants_model_training") == "Yes":
        reasons.append("Data rights: partner wants to train AI models on IDC data; "
                       "needs leadership and legal review")
    if CLOSE_CALL_BAND[0] <= total <= CLOSE_CALL_BAND[1]:
        reasons.append(f"Close call: score {total} is just under the Priority threshold of {PRIORITY_THRESHOLD}")
    missing = [label for field, label in SCORING_INPUTS.items() if is_missing(opp.get(field))]
    if missing:
        reasons.append(f"Missing scoring inputs ({', '.join(missing)}); score may be understated")
    return reasons


def score_opportunity(opp: dict) -> dict:
    """Score one opportunity and return the total, tier, reasons, review flags, and missing fields."""
    parts = {
        "partnership_model": _lookup("Partnership model", opp.get("partnership_model"), MODEL_POINTS),
        "partner_type": score_partner_type(opp.get("partner_type")),
        "revenue_model": _lookup("Revenue model", opp.get("revenue_model"), REVENUE_POINTS),
        "deal_value": score_value(opp.get("est_annual_value_usd")),
        "integration_effort": _lookup("Integration effort", opp.get("integration_effort"), EFFORT_POINTS),
        "source": _lookup("Source", opp.get("source"), SOURCE_POINTS),
    }
    breakdown = {name: points for name, (points, _) in parts.items()}
    total = sum(breakdown.values())
    review_reasons = review_flags(opp, total)
    return {
        "opportunity_id": opp.get("opportunity_id"),
        "company": opp.get("company"),
        "score": total,
        "tier": assign_tier(total),
        "breakdown": breakdown,
        "reasons": [reason for _, reason in parts.values()],
        "missing_fields": [f for f in REQUIRED_FIELDS if is_unknown(f, opp.get(f))],
        "needs_review": bool(review_reasons),
        "review_reasons": review_reasons,
        "route_to_sales": opp.get("partnership_model") == "Client request",
    }
