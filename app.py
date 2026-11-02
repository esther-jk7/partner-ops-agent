"""Streamlit dashboard for the Partner Ops Agent."""

import json

import pandas as pd
import streamlit as st

from src.db import get_connection
from src.followup import group_actionable
from src.followup_graph import run_followup
from src.hygiene import POST_SIGNATURE_STAGES, find_issues
from src.scoring import MAX_SCORE


def md(text) -> str:
    """Escape dollar signs so Streamlit doesn't render amounts as math."""
    return str(text).replace("$", "\\$")


st.set_page_config(page_title="Partner Ops Agent", layout="wide")
st.title("Partner Ops Agent")
st.caption("Partner qualification, pipeline hygiene before and after signature, and fact-checked follow-ups "
           "for a partnerships team. All companies and people in this data are fictional.")

conn = get_connection()
triage_df = pd.read_sql_query("""
    SELECT o.opportunity_id, o.company, o.partner_type, o.partnership_model, o.region,
           o.est_annual_value_usd, t.score, t.tier, t.rationale, t.next_action, t.reasons,
           t.needs_review, t.review_reasons, t.route_to_sales, t.explanation_source,
           p.stage, p.owner
    FROM opportunities o
    JOIN triage_results t ON o.opportunity_id = t.opportunity_id
    JOIN pipeline p ON o.opportunity_id = p.opportunity_id
    ORDER BY t.score DESC
""", conn)
triage_df["flag"] = [
    "Route to sales" if route else "Needs review" if review else ""
    for route, review in zip(triage_df["route_to_sales"], triage_df["needs_review"])
]

held = set(triage_df.loc[triage_df["flag"] != "", "opportunity_id"])
issues = find_issues(conn)
all_flagged = group_actionable(issues)
flagged = {opp_id: items for opp_id, items in all_flagged.items() if opp_id not in held}
held_back = [opp_id for opp_id in all_flagged if opp_id in held]

cols = st.columns(6)
cols[0].metric("Opportunities", len(triage_df))
cols[1].metric("Priority", int((triage_df["tier"] == "Priority").sum()))
cols[2].metric("Needs review", int((triage_df["flag"] == "Needs review").sum()))
cols[3].metric("Route to sales", int((triage_df["flag"] == "Route to sales").sum()))
cols[4].metric("High-severity issues", sum(i["severity"] == "High" for i in issues))
cols[5].metric("Follow-ups needed", len(flagged))

tab_triage, tab_hygiene, tab_followup = st.tabs(["Triage", "Pipeline hygiene", "Follow-up drafts"])

with tab_triage:
    tiers = st.multiselect("Filter by tier", ["Priority", "Nurture", "Deprioritize"],
                           default=["Priority", "Nurture", "Deprioritize"])
    action_only = st.checkbox("Only show items flagged for review or routing")
    view = triage_df[triage_df["tier"].isin(tiers)]
    if action_only:
        view = view[view["flag"] != ""]
    display = view.assign(owner=view["owner"].fillna("Unassigned"), region=view["region"].fillna("Missing"),
                          partnership_model=view["partnership_model"].fillna("Missing"))
    st.dataframe(
        display[["company", "partnership_model", "partner_type", "region", "est_annual_value_usd",
                 "score", "tier", "flag", "stage", "owner"]],
        hide_index=True, width="stretch",
        column_config={
            "company": "Company",
            "partnership_model": "Partnership model",
            "partner_type": "Partner type",
            "region": "Region",
            "est_annual_value_usd": st.column_config.NumberColumn("Est. annual value (USD)", format="localized"),
            "score": st.column_config.NumberColumn(f"Score (out of {MAX_SCORE})"),
            "tier": "Tier",
            "flag": "Flag",
            "stage": "Stage",
            "owner": "Owner",
        },
    )
    for _, row in view.iterrows():
        label = f"{row['company']}: {row['tier']} ({row['score']}/{MAX_SCORE})"
        if row["flag"]:
            label += f" · {row['flag']}"
        with st.expander(label):
            if row["route_to_sales"]:
                st.info("Route to sales: this reads as a client request, not a partnership.")
            for reason in json.loads(row["review_reasons"] or "[]"):
                st.warning(md(reason))
            st.markdown(f"**Summary:** {md(row['rationale'])}")
            st.markdown("**Scoring reasons (from the rules):**")
            st.markdown("\n".join(f"- {md(r)}" for r in json.loads(row["reasons"] or "[]")))
            if row["stage"] in POST_SIGNATURE_STAGES:
                st.markdown(f"**Next action:** Already signed (stage: {row['stage']}). The score above is from "
                            "qualification; current next steps come from activation tracking.")
                partner_issues = [i for i in issues if i["opportunity_id"] == row["opportunity_id"]]
                if partner_issues:
                    st.markdown("\n".join(f"- **{i['issue']}:** {md(i['detail'])}" for i in partner_issues))
                else:
                    st.success("No open activation issues.")
            else:
                st.markdown(f"**Next action:** {md(row['next_action'])}")
            st.caption(f"Summary written by: {row['explanation_source']}")

with tab_hygiene:
    if issues:
        st.dataframe(pd.DataFrame(issues)[["severity", "company", "tier", "issue", "detail"]],
                     hide_index=True, width="stretch",
                     column_config={"severity": "Severity", "company": "Company", "tier": "Tier", "issue": "Issue", "detail": "Detail"})
    else:
        st.success("No pipeline issues found.")

with tab_followup:
    if held_back:
        names = ", ".join(triage_df.set_index("opportunity_id").loc[held_back, "company"])
        st.info(f"Not drafted (on review hold or routed to sales): {names}")
    if not flagged:
        st.success("No deals need a follow-up right now.")
    else:
        companies = {opp_id: items[0]["company"] for opp_id, items in flagged.items()}
        opp_id = st.selectbox("Choose a flagged deal", list(companies), format_func=companies.get)
        st.write("**Problems found:** " + "; ".join(f"{i['issue']} ({i['detail']})" for i in flagged[opp_id]))

        drafts = st.session_state.setdefault("drafts", {})
        if st.button("Draft follow-up email"):
            with st.spinner("Drafting and fact-checking..."):
                drafts[opp_id] = run_followup(conn, opp_id, flagged[opp_id])

        if opp_id in drafts:
            draft = drafts[opp_id]
            if draft["passed"]:
                st.success(f"Passed fact-check after {draft['attempts']} attempt(s)")
            else:
                st.warning(f"Needs human review: still failing the fact-check after {draft['attempts']} attempts")
            st.text_input("Subject", draft["subject"])
            st.text_area("Body (edit before sending)", draft["body"], height=260)
            st.info(f"Internal note: {draft['internal_note']}")
            with st.expander("Fact-check log"):
                for h in draft["history"]:
                    st.markdown(f"**Attempt {h['attempt']}:** {'Passed' if h['passed'] else 'Failed'}")
                    for p in h["problems"]:
                        st.markdown(f"- {p}")
