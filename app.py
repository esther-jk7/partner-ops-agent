"""Streamlit dashboard for the Partner Ops Agent."""

import pandas as pd
import streamlit as st

from src.db import get_connection
from src.followup import group_actionable
from src.followup_graph import run_followup
from src.hygiene import find_issues

st.set_page_config(page_title="Partner Ops Agent", layout="wide")
st.title("Partner Ops Agent")
st.caption("Automated triage, pipeline hygiene, and follow-up drafting for a partnerships team")

conn = get_connection()
triage_df = pd.read_sql_query("""
    SELECT o.opportunity_id, o.company, o.partner_type, o.region, o.est_annual_value_usd,
           t.score, t.tier, t.rationale, t.next_action, p.stage, p.owner
    FROM opportunities o
    JOIN triage_results t ON o.opportunity_id = t.opportunity_id
    JOIN pipeline p ON o.opportunity_id = p.opportunity_id
    ORDER BY t.score DESC
""", conn)
issues = find_issues(conn)
flagged = group_actionable(issues)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Opportunities", len(triage_df))
col2.metric("Priority deals", int((triage_df["tier"] == "Priority").sum()))
col3.metric("High-severity issues", sum(i["severity"] == "High" for i in issues))
col4.metric("Follow-ups needed", len(flagged))

tab_triage, tab_hygiene, tab_followup = st.tabs(["Triage", "Pipeline hygiene", "Follow-up drafts"])

with tab_triage:
    tiers = st.multiselect("Filter by tier", ["Priority", "Nurture", "Deprioritize"],
                           default=["Priority", "Nurture", "Deprioritize"])
    view = triage_df[triage_df["tier"].isin(tiers)]
    display = view.assign(owner=view["owner"].fillna("Unassigned"), region=view["region"].fillna("Missing"))
    st.dataframe(
        display[["company", "partner_type", "region", "est_annual_value_usd", "score", "tier", "stage", "owner"]],
        hide_index=True, width="stretch",
        column_config={
            "company": "Company",
            "partner_type": "Partner type",
            "region": "Region",
            "est_annual_value_usd": st.column_config.NumberColumn("Est. annual value (USD)", format="localized"),
            "score": st.column_config.NumberColumn("Score (out of 90)"),
            "tier": "Tier",
            "stage": "Stage",
            "owner": "Owner",
        },
    )
    for _, row in view.iterrows():
        with st.expander(f"{row['company']}: {row['tier']} ({row['score']}/90)"):
            st.markdown(f"**Why this tier:** {row['rationale']}")
            st.markdown(f"**Next action:** {row['next_action']}")

with tab_hygiene:
    if issues:
        st.dataframe(pd.DataFrame(issues)[["severity", "company", "tier", "issue", "detail"]],
                     hide_index=True, width="stretch",
                     column_config={"severity": "Severity", "company": "Company", "tier": "Tier", "issue": "Issue", "detail": "Detail"})
    else:
        st.success("No pipeline issues found.")

with tab_followup:
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
