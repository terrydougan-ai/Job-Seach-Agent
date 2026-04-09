import streamlit as st
import os
import json
import requests
import pandas as pd
from bs4 import BeautifulSoup
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

# Load credentials - works both locally and in Streamlit Cloud
load_dotenv()
openai_key = os.getenv("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY")
sheet_id = os.getenv("GOOGLE_SHEET_ID") or st.secrets.get("GOOGLE_SHEET_ID")
serper_key = os.getenv("SERPER_API_KEY") or st.secrets.get("SERPER_API_KEY")
try:
    gmail_address = st.secrets["GMAIL_ADDRESS"]
    gmail_password = st.secrets["GMAIL_APP_PASSWORD"]
except:
    gmail_address = os.getenv("GMAIL_ADDRESS", "")
    gmail_password = os.getenv("GMAIL_APP_PASSWORD", "")
client = OpenAI(api_key=openai_key)

# ─────────────────────────────────────────
# RESUME & PREFERENCES
# ─────────────────────────────────────────

RESUME = """
TERRY DOUGAN
VP / Head of Technology Program Management & Product Operations | Chief of Staff to CTO/CPO | Strategy to Execution

PROFILE:
Technology operations leader with a track record of serving as the operational right-hand to CTOs and CPOs 
in fast-moving engineering and product organizations. Specializes in translating executive priorities into 
clear, trackable initiatives; owning operating cadences, cross-functional alignment, KPI frameworks, and 
the accountability structures that keep complex technology organizations executing with discipline.

Deep experience supporting executive decision-making, preparing board and leadership materials, driving OKRs 
and investment trade-offs. AI-fluent: led delivery governance for 30+ LLM, RAG, and Generative AI initiatives 
in production. Proven ability to maintain execution momentum through sustained ambiguity.

EXPERIENCE:
- VP, Product & Delivery Operations, Clarivate (2023-2025): Chief of Staff to CTO across 1,000+ person 
  global tech org. $120M+ portfolio. Team of 40+. Led 30+ AI/ML initiatives to production. Built portfolio 
  dashboards, OKR frameworks, delivery improvement programs. Improved renewal rates 83%->92% on $60M+ ARR products.
- VP, Product Operations & Launch Readiness, CPA Global/Clarivate (2020-2023): Chief of Staff to 3 successive 
  CPOs. $400M+ R&D portfolio. 200+ products. Shifted strategic investment from 10% to 35%.
- Director of Technology, Thomson Reuters (2016-2020): Led 50+ person global engineering org. AWS migration, 
  platform modernization, 99.9%+ uptime, M&A integration.
- Director, Technology Program Management, Thomson Reuters (2014-2016): Global PMO, $250M revenue BU.
- Senior TPM, Software Engineer, Thomson Reuters (2006-2014)
- Consultant/Manager, Accenture (1994-2000): SAP/Oracle enterprise solutions.
- Software Engineer, Procter & Gamble (1993)

EDUCATION: B.S. Systems & Control Engineering, Case Western Reserve University (Cum Laude, Tau Beta Pi)
SKILLS: Python, SQL, AWS, Tableau, PowerBI, Snowflake, Jira, Smartsheet, SAFe/LPM, Scrum, Pendo
AI CERTS: Deep Learning Specialization, Generative AI for Everyone, AI Python (DeepLearning.AI 2025)
"""

PREFERENCES = """
TARGET ROLES:
- Director / Senior Director / VP / Head of: Technical Program Management, Program/Portfolio/PMO (strategic), 
  Product Operations, Transformation/Strategic Execution
- Chief of Staff to CTO/CPO/Head of Engineering/Product ONLY if: strategic + execution-focused, owns portfolio 
  prioritization, operating cadence, cross-functional alignment
- EXCLUDE: admin/comms-heavy CoS roles, pure PMO/administrative roles

COMPANY PREFERENCES:
- High priority: Mission-driven (women in tech, STEM, healthcare/wellness), AI/data/platform companies, 
  personal health/wellness tech
- Strong fit: Data/analytics platforms, Enterprise SaaS/platform companies, AI-native or AI-enabled companies
- Conditional: Consulting/research ONLY if directly tied to software/data/tech execution

COMPENSATION:
- Base: $200K+
- Total Comp: $250K-$400K+ preferred
- Flex allowed for exceptional scope or strong mission alignment

LOCATION: Remote (US) preferred. Also: Detroit metro, Columbus, Cincinnati

SCORING CRITERIA (0-5 scale):
- Culture Score: Leadership quality, employee satisfaction, mission alignment, Glassdoor signals
- Comp Score: How well total comp meets targets ($250K-$400K+)
- Scope Score: Strategic influence, team leadership, executive exposure, portfolio ownership
- Effort Score: Estimated fit effort required (5=easy fit, 1=major stretch)
- Fit Score: Overall alignment to target role type and company preferences
- Final Score: Weighted overall score
"""

# ─────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────

def serper_search(query):
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": serper_key, "Content-Type": "application/json"},
            json={"q": query, "num": 5}
        )
        results = response.json()
        snippets = []
        for r in results.get("organic", []):
            snippets.append(f"{r.get('title', '')} - {r.get('snippet', '')}")
        return "\n".join(snippets) if snippets else "No results found."
    except Exception as e:
        return f"Search error: {e}"

def lookup_company_signals(company_name):
    glassdoor_data = serper_search(f"{company_name} Glassdoor overall rating CEO approval site:glassdoor.com")
    blind_data = serper_search(f'site:teamblind.com "{company_name}"')
    if "teamblind.com" not in blind_data.lower():
        blind_data = "No Blind data found for this company."
    return glassdoor_data, blind_data

def score_role(job_description):

    # -- PASS 1: Full scoring first using complete JD --
    prompt = f"""
You are an expert career advisor evaluating a job opportunity for a senior technology executive.

CANDIDATE RESUME:
{RESUME}

CANDIDATE PREFERENCES & SCORING CRITERIA:

{build_preferences(load_settings())}

JOB DESCRIPTION TO EVALUATE:
{job_description}

Evaluate this role and return a JSON object with EXACTLY these fields.
Return ONLY the JSON - no explanation, no markdown, no backticks.

{{
  "company": "The EMPLOYER name - the company that posted this job and will employ the person. NEVER return a software tool or technology as the company name (e.g. Microsoft Office, Smartsheet, Salesforce are tools not employers). Look for phrases like 'at [Company]', 'join [Company]', '[Company] offers benefits' to identify the true employer.",
  "role_title": "Exact role title from JD",
  "location": "Location or Remote",
  "employment_type": "Full-time/Part-time/Contract",
  "expected_base": "Base salary range if posted, else 'Not posted'",
  "expected_bonus_pct": "Bonus % if posted, else ''",
  "expected_equity": "Equity value if posted, else ''",
  "comp_signal": "One line: does comp meet target?",
  "equity_yn": "Yes/No/TBD",
  "glassdoor_rating": "To be updated",
  "ceo_approval": "To be updated",
  "blind_informed_flag": "To be updated",
  "leadership_culture_signal": "To be updated",
  "company_description": "One sentence description of the company",
  "why_its_a_fit": "2-3 sentences on why this role fits Terry's background",
  "where_it_falls_short": "2-3 sentences on gaps or misalignments",
  "growth": "High/Medium/Low/Unknown",
  "culture_score": 0.0,
  "comp_score": 0.0,
  "scope_score": 0.0,
  "effort_score": 0.0,
  "fit_score": 0.0,
  "final_score": 0.0,
  "recommended_action": "Apply Immediately / Selective Apply / Do Not Apply / Research More",
  "priority": "Very High / High / Medium-High / Medium / Low",
  "current_status": "To Review",
  "date_added": "{datetime.today().strftime('%m/%d/%Y')}"
}}
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": """You are an expert career advisor. Return only valid JSON. CRITICAL: You MUST replace ALL score fields with actual float values between 0.0 and 5.0. Never return 0.0 for any score unless the role truly deserves a zero. Scores to fill in: culture_score, comp_score, scope_score, effort_score, fit_score, final_score."""},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2
    )

    raw = response.choices[0].message.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    scored = json.loads(raw)

    # -- PASS 2: Use scored company name for accurate lookup --
    company_name = scored["company"]
    glassdoor_data, blind_data = lookup_company_signals(company_name)

    # -- PASS 3: Enrich culture fields with real signals --
    enrich_prompt = f"""
Based on this Glassdoor and Blind data for {company_name}, return ONLY a JSON object 
with these fields updated. Return ONLY JSON, no explanation.

LIVE GLASSDOOR DATA:
{glassdoor_data}

LIVE BLIND DATA:
{blind_data}

{{
  "glassdoor_rating": "Extract ONLY from live data. If not found return 'Not found'",
  "ceo_approval": "Extract ONLY from live data. If not found return 'Not found'",
  "blind_informed_flag": "Extract ONLY from live data. If not found return 'Not found'",
  "leadership_culture_signal": "2-3 sentence summary based on Glassdoor and Blind data combined",
  "culture_score": "A float between 0.0 and 5.0 based on the Glassdoor rating, CEO approval, and Blind sentiment. A 4.0+ Glassdoor rating with high CEO approval should score 3.5-4.5. If no data found return 2.5 as neutral."
}}
"""

    enrich_response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "Return only valid JSON. For culture_score return a float number between 0.0 and 5.0, not a string."},
            {"role": "user", "content": enrich_prompt}
        ],
        temperature=0.1
    )

    enrich_raw = enrich_response.choices[0].message.content.strip()
    enrich_raw = enrich_raw.replace("```json", "").replace("```", "").strip()
    enriched = json.loads(enrich_raw)

    # Merge enriched fields into scored
    scored.update(enriched)

    return scored, company_name, glassdoor_data, blind_data

def write_to_sheet(scored, job_url=""):
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    # Use Streamlit secrets in cloud, fall back to local file
    try:
        creds = Credentials.from_service_account_info(
            st.secrets["gcp_service_account"],
            scopes=scopes
        )
    except:
        creds = Credentials.from_service_account_file(
            "google_credentials.json",
            scopes=scopes
        )
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(sheet_id)
    worksheet = spreadsheet.sheet1
    data = worksheet.get_all_values()
    headers = data[0]

    column_map = {
        "Company": scored.get("company", ""),
        "Role Title": scored.get("role_title", ""),
        "Location": scored.get("location", ""),
        "Employment Type": scored.get("employment_type", ""),
        "Expected Base ($)": scored.get("expected_base", ""),
        "Expected Bonus (%)": scored.get("expected_bonus_pct", ""),
        "Expected Equity (4yr $)": scored.get("expected_equity", ""),
        "Comp Signal (Base + Bonus)": scored.get("comp_signal", ""),
        "Equity (Y/N/TBD)": scored.get("equity_yn", ""),
        "Glassdoor Rating": scored.get("glassdoor_rating", ""),
        "CEO Approval": scored.get("ceo_approval", ""),
        "Blind informed Flag": scored.get("blind_informed_flag", ""),
        "Leadership & Culture Signal": scored.get("leadership_culture_signal", ""),
        "Company Description": scored.get("company_description", ""),
        "Why Its a Fit": scored.get("why_its_a_fit", ""),
        "Where it Falls Short": scored.get("where_it_falls_short", ""),
        "Growth": scored.get("growth", ""),
        "Culture Score": scored.get("culture_score", ""),
        "Comp Score": scored.get("comp_score", ""),
        "Scope Score": scored.get("scope_score", ""),
        "Effort Score": scored.get("effort_score", ""),
        "Fit Score": scored.get("fit_score", ""),
        "Final Score": scored.get("final_score", ""),
        "Recommended Action": scored.get("recommended_action", ""),
        "Priority": scored.get("priority", ""),
        "Current Status": scored.get("current_status", "To Review"),
        "Date Added to Tracker": scored.get("date_added", ""),
        "Date Applied": scored.get("date_applied", ""),
        "Application Link": job_url,
    }

    new_row = [column_map.get(h, "") for h in headers]
    worksheet.append_row(new_row, value_input_option="USER_ENTERED")

import json
from pathlib import Path

BRIEFING_FILE = "last_briefing.json"

def save_briefing(summary, today, metrics_df, active_count):
    # Convert Period objects to strings for JSON serialization
    metrics_save = metrics_df.copy()
    metrics_save["Week"] = metrics_save["Week"].astype(str)
    data = {
        "summary": summary,
        "date": today,
        "active_count": active_count,
        "metrics": metrics_save.to_dict(orient="records"),
        "metrics_columns": metrics_save.columns.tolist()
    }
    with open(BRIEFING_FILE, "w") as f:
        json.dump(data, f)

def load_briefing():
    if Path(BRIEFING_FILE).exists():
        with open(BRIEFING_FILE, "r") as f:
            data = json.load(f)
        metrics_df = pd.DataFrame(data["metrics"], columns=data["metrics_columns"])
        return data["summary"], data["date"], metrics_df, data["active_count"]
    return None, None, None, None

SETTINGS_FILE = "settings.json"

DEFAULT_SETTINGS = {
    "target_base": 200000,
    "target_total_comp_min": 250000,
    "target_total_comp_max": 400000,
    "locations": "Remote (US), Detroit metro, Columbus, Cincinnati",
    "target_roles": "Director / Senior Director / VP / Head of: Technical Program Management, Program/Portfolio/PMO (strategic), Product Operations, Transformation/Strategic Execution\nChief of Staff to CTO/CPO/Head of Engineering/Product ONLY if: strategic + execution-focused, owns portfolio prioritization, operating cadence, cross-functional alignment",
    "exclude_roles": "Admin/comms-heavy CoS roles, pure PMO/administrative roles",
    "company_high_priority": "Mission-driven (women in tech, STEM, healthcare/wellness), AI/data/platform companies, personal health/wellness tech",
    "company_strong_fit": "Data/analytics platforms, Enterprise SaaS/platform companies, AI-native or AI-enabled companies",
    "company_conditional": "Consulting/research ONLY if directly tied to software/data/tech execution",
    "comp_flex_note": "Flex allowed for exceptional scope or strong mission alignment",
    "scoring_notes": "Culture Score: Leadership quality, employee satisfaction, mission alignment, Glassdoor signals\nComp Score: How well total comp meets targets\nScope Score: Strategic influence, team leadership, executive exposure, portfolio ownership\nEffort Score: Estimated fit effort required (5=easy fit, 1=major stretch)\nFit Score: Overall alignment to target role type and company preferences\nFinal Score: Weighted overall score"
}

def load_settings():
    if Path(SETTINGS_FILE).exists():
        with open(SETTINGS_FILE, "r") as f:
            saved = json.load(f)
        # Merge with defaults in case new fields were added
        settings = DEFAULT_SETTINGS.copy()
        settings.update(saved)
        return settings
    return DEFAULT_SETTINGS.copy()

def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)

def build_preferences(settings):
    return f"""
TARGET ROLES:
- {settings['target_roles']}
- EXCLUDE: {settings['exclude_roles']}

COMPANY PREFERENCES:
- High priority: {settings['company_high_priority']}
- Strong fit: {settings['company_strong_fit']}
- Conditional: {settings['company_conditional']}

COMPENSATION:
- Base: ${settings['target_base']:,}+
- Total Comp: ${settings['target_total_comp_min']:,}-${settings['target_total_comp_max']:,}+ preferred
- {settings['comp_flex_note']}

LOCATION: {settings['locations']}

SCORING CRITERIA (0-5 scale):
{settings['scoring_notes']}
"""

settings = load_settings()
PREFERENCES = build_preferences(settings)

# ─────────────────────────────────────────
# STREAMLIT UI
# ─────────────────────────────────────────

st.set_page_config(page_title="Job Search Command Center", page_icon="🎯", layout="wide")

st.markdown("""
    <style>
    /* Metric label - larger and bolder */
    [data-testid="stMetricLabel"] p {
        font-size: 1.1rem !important;
        font-weight: 600 !important;
        color: #2c3e50 !important;
    }
    /* Metric value - smaller and wrapping */
    [data-testid="stMetricValue"] div {
        font-size: 0.95rem !important;
        font-weight: 400 !important;
        white-space: normal !important;
        word-wrap: break-word !important;
        overflow: visible !important;
        text-overflow: unset !important;
        line-height: 1.4 !important;
    }
    </style>
""", unsafe_allow_html=True)

# Sidebar navigation
st.sidebar.title("🎯 Job Search")
st.sidebar.markdown("---")
page = st.sidebar.radio("Navigate", ["🎯 Score Role", "📋 Job Tracker", "📬 Weekly Briefing", "⚙️ Settings"])

if page == "🎯 Score Role":
    st.title("🎯 Job Role Scorer")
    st.markdown("Paste a job description to score it against your resume and preferences.")

    # Input form
    with st.form("scorer_form"):
        job_description = st.text_area(
            "Paste Job Description",
            height=300,
            placeholder="Paste the full job description here..."
        )
        job_url = st.text_input(
            "Application Link (optional)",
            placeholder="https://jobs.ashbyhq.com/company/job-id"
        )
        submitted = st.form_submit_button("🔍 Score This Role", use_container_width=True)

    # Score the role
    if submitted:
        if not job_description.strip():
            st.error("Please paste a job description.")
        else:
            with st.spinner("Scoring role - looking up Glassdoor, Blind, and running analysis..."):
                try:
                    scored, company_name, glassdoor_data, blind_data = score_role(job_description)

                    # Store in session state
                    st.session_state["scored"] = scored
                    st.session_state["job_url"] = job_url
                    st.session_state["scored_success"] = True

                except Exception as e:
                    st.error(f"Scoring failed: {e}")
                    st.session_state["scored_success"] = False

    # Display results
    if st.session_state.get("scored_success"):
        scored = st.session_state["scored"]

        st.divider()
        st.subheader(f"📊 Results: {scored.get('company')} - {scored.get('role_title')}")

        def stat_card(label, value):
            st.markdown(f"""
                <div style="padding: 4px 0px 16px 0px;">
                    <p style="font-size: 1.1rem; font-weight: 600; color: #2c3e50; margin-bottom: 4px;">{label}</p>
                    <p style="font-size: 0.95rem; font-weight: 400; color: #444; line-height: 1.4; margin: 0;">{value}</p>
                </div>
            """, unsafe_allow_html=True)

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            stat_card("Final Score", f"{scored.get('final_score')} / 5")
        with col2:
            stat_card("Priority", scored.get('priority'))
        with col3:
            stat_card("Recommended Action", scored.get('recommended_action'))
        with col4:
            stat_card("Comp Signal", scored.get('comp_signal'))

        st.divider()

        # Scores breakdown
        st.subheader("Score Breakdown")
        sc1, sc2, sc3, sc4, sc5 = st.columns(5)
        sc1.metric("Culture", scored.get('culture_score'))
        sc2.metric("Comp", scored.get('comp_score'))
        sc3.metric("Scope", scored.get('scope_score'))
        sc4.metric("Effort", scored.get('effort_score'))
        sc5.metric("Fit", scored.get('fit_score'))

        st.divider()

        # Fit analysis
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("✅ Why It's a Fit")
            st.write(scored.get('why_its_a_fit'))
        with col2:
            st.subheader("⚠️ Where It Falls Short")
            st.write(scored.get('where_it_falls_short'))

        st.divider()

        # Company signals
        st.subheader("🏢 Company Signals")
        sig1, sig2, sig3, sig4 = st.columns(4)
        sig1.metric("Glassdoor Rating", scored.get('glassdoor_rating'))
        sig2.metric("CEO Approval", scored.get('ceo_approval'))
        sig3.metric("Blind Signal", scored.get('blind_informed_flag'))
        sig4.metric("Growth", scored.get('growth'))

        st.info(f"**Culture Signal:** {scored.get('leadership_culture_signal')}")
        st.info(f"**Company:** {scored.get('company_description')}")

        st.divider()

        # Role details
        with st.expander("📋 Full Role Details"):
            detail1, detail2 = st.columns(2)
            with detail1:
                st.write(f"**Company:** {scored.get('company')}")
                st.write(f"**Role:** {scored.get('role_title')}")
                st.write(f"**Location:** {scored.get('location')}")
                st.write(f"**Employment Type:** {scored.get('employment_type')}")
            with detail2:
                st.write(f"**Expected Base:** {scored.get('expected_base')}")
                st.write(f"**Bonus:** {scored.get('expected_bonus_pct')}")
                st.write(f"**Equity:** {scored.get('expected_equity')}")
                st.write(f"**Equity Y/N:** {scored.get('equity_yn')}")

        st.divider()

        # Write to sheet
        st.subheader("💾 Save to Google Sheet")
        st.write("Review the scores above - if they look good, save this role to your tracker.")

        if st.button("✅ Save to Google Sheet", use_container_width=True, type="primary"):
            with st.spinner("Writing to Google Sheet..."):
                try:
                    write_to_sheet(scored, st.session_state.get("job_url", ""))
                    st.success(f"✅ '{scored.get('role_title')}' at {scored.get('company')} saved to your tracker!")
                    st.balloons()
                    st.session_state["scored_success"] = False
                except Exception as e:
                    st.error(f"Failed to write to sheet: {e}")

elif page == "📋 Job Tracker":
    st.title("📋 Job Tracker")
    st.markdown("View and update your job search pipeline.")
    sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
    st.markdown(f"📊 [Open Google Sheet]({sheet_url})")

    # ── Load data from Google Sheet ──
    @st.cache_data(ttl=30)
    def load_tracker():
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        try:
            creds = Credentials.from_service_account_info(
                st.secrets["gcp_service_account"],
                scopes=scopes
            )
        except:
            creds = Credentials.from_service_account_file(
                "google_credentials.json",
                scopes=scopes
            )
        gc = gspread.authorize(creds)
        spreadsheet = gc.open_by_key(sheet_id)
        worksheet = spreadsheet.sheet1
        data = worksheet.get_all_values()
        headers = data[0]
        rows = data[1:]
        df = pd.DataFrame(rows, columns=headers)
        df.columns = [str(h).strip() for h in df.columns]
        df = df[df["Company"].str.strip() != ""]
        df["_row_index"] = range(2, len(df) + 2)  # 1-indexed + header row
        return df, worksheet

    import pandas as pd

    try:
        df, worksheet = load_tracker()
    except Exception as e:
        st.error(f"Failed to load tracker: {e}")
        st.stop()

    # ── Filters ──
    st.sidebar.markdown("---")
    st.sidebar.subheader("🔍 Filters")

    all_statuses = sorted(df["Current Status"].unique().tolist())
    selected_statuses = st.sidebar.multiselect(
        "Status",
        options=all_statuses,
        default=[s for s in all_statuses if s not in [
            "Closed / Rejected", "Closed / No longer posted",
            "Not Interested", "Do Not Apply", "Pass"
        ]]
    )

    all_priorities = sorted([p for p in df["Priority"].unique().tolist() if p.strip()])
    selected_priorities = st.sidebar.multiselect(
        "Priority",
        options=all_priorities,
        default=all_priorities
    )

    search_term = st.sidebar.text_input("Search Company or Role", "")

    # ── Apply filters ──
    filtered = df.copy()
    if selected_statuses:
        filtered = filtered[filtered["Current Status"].isin(selected_statuses)]
    if selected_priorities:
        filtered = filtered[filtered["Priority"].isin(selected_priorities)]
    if search_term:
        filtered = filtered[
            filtered["Company"].str.contains(search_term, case=False, na=False) |
            filtered["Role Title"].str.contains(search_term, case=False, na=False)
        ]

    st.markdown(f"**{len(filtered)} roles** matching your filters")
    st.divider()

    # ── Status color mapping ──
    status_colors = {
        "Applied": "🟢",
        "To Review": "⚪",
        "Will Apply": "🔵",
        "Closed / Rejected": "🔴",
        "Closed / No longer posted": "🔴",
        "Not Interested": "⛔",
        "Recruiter Outreach": "🟡",
        "In Progress": "🟢",
    }

# ── Display roles grouped by status ──
    # Define status display order
    status_order = [
        "Applied",
        "In Progress", 
        "Will Apply",
        "To Review",
        "Recruiter Outreach",
        "Not Interested",
        "Do Not Apply",
        "Pass",
        "Closed / Rejected",
        "Closed / No longer posted",
    ]

    # Sort by status order, unknown statuses go to end
    filtered["_status_order"] = filtered["Current Status"].apply(
        lambda x: status_order.index(x) if x in status_order else 999
    )
    
    # Convert Final Score to numeric for sorting, empty scores go to bottom
    filtered["_final_score_num"] = pd.to_numeric(filtered["Final Score"], errors="coerce").fillna(0)
    filtered = filtered.sort_values(["_status_order", "_final_score_num"], ascending=[True, False])

    # Group and display
    current_group = None
    for _, row in filtered.iterrows():
        status = row.get("Current Status", "Unknown")
        
        # Print group header when status changes
        if status != current_group:
            current_group = status
            status_icon_header = status_colors.get(status, "⚪")
            count = len(filtered[filtered["Current Status"] == status])
            st.markdown(f"### {status_icon_header} {status} ({count})")
            st.markdown("---")

        status_icon = status_colors.get(row.get("Current Status", ""), "⚪")
        final_score = row.get("Final Score", "")
        priority = row.get("Priority", "")
        current_status = row.get("Current Status", "")
        date_applied = row.get("Date Applied", "")

        expander_label = f"{status_icon} {row['Company']} — {row['Role Title']}  |  Score: {final_score}  |  Priority: {priority}  |  Status: {current_status}   | Date Applied: {date_applied}"
        
        with st.expander(expander_label):
            col1, col2 = st.columns(2)
            with col1:
                st.write(f"**Location:** {row.get('Location', '')}")
                st.write(f"**Expected Base:** {row.get('Expected Base ($)', '')}")
                st.write(f"**Comp Signal:** {row.get('Comp Signal (Base + Bonus)', '')}")
                st.write(f"**Glassdoor Rationg:** {row.get('Glassdoor Rating', '')}")
                st.write(f"**Why It Is A Fit:** {row.get('Why Its a Fit')}")
            with col2:
                st.write(f"**Recommended Action:** {row.get('Recommended Action', '')}")
                st.write(f"**Date Added:** {row.get('Date Added to Tracker', '')}")
                app_link = row.get('Application Link', '')
                if app_link.strip():
                    st.markdown(f"**Application Link:** [Open Job Posting]({app_link})")
                else:
                    st.write("**Application Link:** Not set")
                st.write(f"**CEO Approval:** {row.get('CEO Approval')}")
                st.write(f"**Where It Falls Short:** {row.get('Where it Falls Short')}")

            st.markdown("---")
            st.markdown("**✏️ Update Fields**")

            status_options = [
                "To Review", "Will Apply", "Applied", "Recruiter Outreach",
                "In Progress", "Closed / Rejected", "Closed / No longer posted",
                "Not Interested", "Do Not Apply", "Pass"
            ]
            current_status_val = row.get("Current Status", "To Review")
            if current_status_val not in status_options:
                status_options.append(current_status_val)

            with st.form(f"update_form_{row['_row_index']}"):
                upd1, upd2 = st.columns(2)
                with upd1:
                    new_status = st.selectbox(
                        "Current Status",
                        status_options,
                        index=status_options.index(current_status_val) if current_status_val in status_options else 0
                    )
                    new_reason = st.text_input(
                        "Reason Not Interested",
                        value=row.get("Reason Not Interested", "")
                    )
                    new_notes = st.text_area(
                        "Notes / Exec Status",
                        value=row.get("Exec Status", ""),
                        height=100
                    )
                    
                with upd2:
                    new_date_applied = st.text_input(
                        "Date Applied",
                        value=row.get("Date Applied", ""),
                        placeholder="MM/DD/YYYY"
                    )
                    new_date_rejected = st.text_input(
                        "Date Rejected",
                        value=row.get("Date Rejected", ""),
                        placeholder="MM/DD/YYYY"
                    )
                    new_app_link = st.text_input(
                       "Application Link",
                        value=row.get("Application Link", ""),
                        placeholder="https://..."
                    )    

                col_save, col_delete = st.columns([1, 1])
                with col_save:
                    save = st.form_submit_button("💾 Save Changes", use_container_width=True)
                with col_delete:
                    delete = st.form_submit_button("🗑️ Delete Row", use_container_width=True)

                if save:
                    try:
                        # Fresh connection for save
                        scopes = [
                            "https://www.googleapis.com/auth/spreadsheets",
                            "https://www.googleapis.com/auth/drive"
                        ]
                        try:
                            creds = Credentials.from_service_account_info(
                                st.secrets["gcp_service_account"],
                                scopes=scopes
                            )
                        except:
                            creds = Credentials.from_service_account_file(
                                "google_credentials.json",
                                scopes=scopes
                            )
                        gc_fresh = gspread.authorize(creds)
                        ws_fresh = gc_fresh.open_by_key(sheet_id).sheet1

                        headers = df.columns.tolist()
                        
                        def update_cell(col_name, value):
                            if col_name in headers:
                                col_idx = headers.index(col_name) + 1
                                ws_fresh.update_cell(row["_row_index"], col_idx, value)

                        update_cell("Current Status", new_status)
                        update_cell("Date Applied", new_date_applied)
                        update_cell("Date Rejected", new_date_rejected)
                        update_cell("Reason Not Interested", new_reason)
                        update_cell("Exec Status", new_notes)
                        update_cell("Application Link", new_app_link)

                        st.success(f"✅ {row['Company']} updated successfully!")
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Failed to save: {e}")
                
                if delete:
                    if not st.session_state.get(f"confirm_delete_{row['_row_index']}"):
                        st.session_state[f"confirm_delete_{row['_row_index']}"] = True
                        st.warning("⚠️ Click Delete Row again to confirm deletion.")
                    else:
                        try:
                            # Fresh connection for delete
                            scopes = [
                                "https://www.googleapis.com/auth/spreadsheets",
                                "https://www.googleapis.com/auth/drive"
                            ]
                            try:
                                creds = Credentials.from_service_account_info(
                                    st.secrets["gcp_service_account"],
                                    scopes=scopes
                                )
                            except:
                                creds = Credentials.from_service_account_file(
                                    "google_credentials.json",
                                    scopes=scopes
                                )
                            gc_fresh = gspread.authorize(creds)
                            ws_fresh = gc_fresh.open_by_key(sheet_id).sheet1
                            ws_fresh.delete_rows(row["_row_index"])
                            st.success(f"✅ {row['Company']} deleted!")
                            st.cache_data.clear()
                            st.session_state.pop(f"confirm_delete_{row['_row_index']}", None)
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Failed to delete: {e}")
elif page == "📬 Weekly Briefing":
    st.title("📬 Weekly Job Search Briefing")
    st.markdown("Generate your weekly pipeline briefing — displays here and emails it to you.")

    # Load last briefing into session state if not already there
    if "briefing_summary" not in st.session_state:
        summary, date, metrics, count = load_briefing()
        if summary:
            st.session_state["briefing_summary"] = summary
            st.session_state["briefing_date"] = date
            st.session_state["briefing_metrics"] = metrics
            st.session_state["briefing_active_count"] = count

    if st.button("🚀 Generate Weekly Briefing", use_container_width=True, type="primary"):
        with st.spinner("Reading your pipeline and generating briefing..."):
            try:
                
                # ── Load tracker data ──
                scopes = [
                    "https://www.googleapis.com/auth/spreadsheets",
                    "https://www.googleapis.com/auth/drive"
                ]
                try:
                    creds = Credentials.from_service_account_info(
                        st.secrets["gcp_service_account"],
                        scopes=scopes
                    )
                except:
                    creds = Credentials.from_service_account_file(
                        "google_credentials.json",
                        scopes=scopes
                    )
                gc_brief = gspread.authorize(creds)
                ws_brief = gc_brief.open_by_key(sheet_id).sheet1
                data = ws_brief.get_all_values()
                headers = data[0]
                rows = data[1:]
                df_brief = pd.DataFrame(rows)
                df_brief.columns = [str(h) for h in headers]

                # ── Filter active roles ──
                exclude_statuses = [
                    "Closed / Rejected", "Closed / No longer posted",
                    "Not Interested", "Do Not Apply", "Pass"
                ]
                active_df = df_brief[~df_brief["Current Status"].isin(exclude_statuses)].copy()
                active_df = active_df.fillna("")

                # ── Weekly metrics ──
                metrics_df = df_brief.copy()
                metrics_df["Date Applied"] = pd.to_datetime(metrics_df["Date Applied"], errors="coerce")
                metrics_df["Date Rejected"] = pd.to_datetime(metrics_df["Date Rejected"], errors="coerce")

                applied_by_week = (
                    metrics_df.dropna(subset=["Date Applied"])
                    .groupby(metrics_df["Date Applied"].dt.to_period("W"))
                    .size()
                    .reset_index(name="Applied")
                )
                applied_by_week.columns = ["Week", "Applied"]

                rejected_by_week = (
                    metrics_df.dropna(subset=["Date Rejected"])
                    .groupby(metrics_df["Date Rejected"].dt.to_period("W"))
                    .size()
                    .reset_index(name="Rejected")
                )
                rejected_by_week.columns = ["Week", "Rejected"]

                weekly_metrics = pd.merge(applied_by_week, rejected_by_week, on="Week", how="outer").fillna(0)
                weekly_metrics["Applied"] = weekly_metrics["Applied"].astype(int)
                weekly_metrics["Rejected"] = weekly_metrics["Rejected"].astype(int)
                weekly_metrics = weekly_metrics.sort_values("Week")

                # ── Format roles for prompt ──
                def format_roles(df):
                    lines = []
                    for _, row in df.iterrows():
                        lines.append(f"""
Company: {row['Company']}
Role: {row['Role Title']}
Priority: {row.get('Priority', '')}
Current Status: {row['Current Status']}
Final Score: {row.get('Final Score', '')}
Recommended Action: {row.get('Recommended Action', '')}
Date Applied: {row.get('Date Applied', '')}
Date Added to Tracker: {row.get('Date Added to Tracker', '')}
Why Its a Fit: {row.get('Why Its a Fit', '')}
Where it Falls Short: {row.get('Where it Falls Short', '')}
---""")
                    return "\n".join(lines)

                formatted_roles = format_roles(active_df)
                today = datetime.today().strftime("%B %d, %Y")

                # ── Generate briefing ──
                brief_prompt = f"""
You are a sharp executive career advisor helping a senior technology leader manage their job search strategically.

Today is {today}.

Here is their current active job pipeline. Review it carefully and produce 
a concise weekly briefing with exactly three sections:

1. PIPELINE SUMMARY
   - How many active roles total
   - How many applied, in progress, not yet applied
   - Any notable patterns or observations worth flagging

2. AT RISK / NEEDS ATTENTION
   - Roles that have gone quiet and may be going cold
   - Applications where no action has been taken and time may be running out
   - Flag any role where Date Applied was more than 2 weeks ago with no update

3. PRIORITIES & RECOMMENDED ACTIONS THIS WEEK
   - Top 3-5 specific actions to take this week, ranked by importance
   - Be direct and specific - name the company and the action
   - Weight recommendations toward roles with highest Final Score
   - If a high-scored role (4.5+) has not been applied to, flag it as urgent
   - For each action include one sentence on WHY it is the priority

Tone: Direct, concise, executive-level. No fluff.
Format: Clean plain text, easy to read.
Length: 400-600 words total.

ACTIVE PIPELINE DATA:
{formatted_roles}
"""

                brief_response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": "You are a sharp executive career advisor."},
                        {"role": "user", "content": brief_prompt}
                    ],
                    temperature=0.4
                )
                summary = brief_response.choices[0].message.content

                # ── Store in session state ──
                st.session_state["briefing_summary"] = summary
                st.session_state["briefing_date"] = today
                st.session_state["briefing_metrics"] = weekly_metrics
                st.session_state["briefing_active_count"] = len(active_df)
                save_briefing(summary, today, weekly_metrics, len(active_df))

                # ── Send email ──
                import smtplib
                from email.mime.text import MIMEText
                from email.mime.multipart import MIMEMultipart

                def send_briefing_email(summary, today, active_count, weekly_metrics):
                    def format_metrics_html(metrics_df):
                        rows = ""
                        for _, row in metrics_df.iterrows():
                            rows += f"""
                            <tr>
                                <td style="padding: 8px 12px; border-bottom: 1px solid #eee;">{str(row['Week'])}</td>
                                <td style="padding: 8px 12px; border-bottom: 1px solid #eee; text-align: center;">{int(row['Applied'])}</td>
                                <td style="padding: 8px 12px; border-bottom: 1px solid #eee; text-align: center;">{int(row['Rejected'])}</td>
                            </tr>"""
                        rows += f"""
                            <tr style="font-weight: bold; background-color: #f8f9fa;">
                                <td style="padding: 8px 12px;">TOTAL</td>
                                <td style="padding: 8px 12px; text-align: center;">{int(metrics_df['Applied'].sum())}</td>
                                <td style="padding: 8px 12px; text-align: center;">{int(metrics_df['Rejected'].sum())}</td>
                            </tr>"""
                        return rows

                    summary_html = summary.replace("\n", "<br>")
                    metrics_rows = format_metrics_html(weekly_metrics)

                    html = f"""
                    <html>
                    <body style="font-family: Arial, sans-serif; max-width: 700px; margin: 0 auto; color: #333;">
                        <div style="background-color: #2c3e50; padding: 20px 30px; border-radius: 8px 8px 0 0;">
                            <h1 style="color: white; margin: 0; font-size: 22px;">Job Search Weekly Briefing</h1>
                            <p style="color: #bdc3c7; margin: 5px 0 0 0;">{today} | {active_count} active roles</p>
                        </div>
                        <div style="background-color: #ffffff; padding: 25px 30px; border: 1px solid #eee;">
                            {summary_html}
                        </div>
                        <div style="background-color: #f8f9fa; padding: 25px 30px; border: 1px solid #eee; border-top: none;">
                            <h2 style="color: #2c3e50; margin-top: 0;">Weekly Pipeline Metrics</h2>
                            <table style="width: 100%; border-collapse: collapse; background: white; border-radius: 6px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                                <thead>
                                    <tr style="background-color: #2c3e50; color: white;">
                                        <th style="padding: 10px 12px; text-align: left;">Week</th>
                                        <th style="padding: 10px 12px; text-align: center;">Applied</th>
                                        <th style="padding: 10px 12px; text-align: center;">Rejected</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {metrics_rows}
                                </tbody>
                            </table>
                        </div>
                        <div style="background-color: #ecf0f1; padding: 12px 30px; border-radius: 0 0 8px 8px; text-align: center;">
                            <p style="color: #7f8c8d; font-size: 12px; margin: 0;">Generated automatically by your job search agent</p>
                        </div>
                    </body>
                    </html>
                    """

                    msg = MIMEMultipart("alternative")
                    msg["Subject"] = f"Job Search Weekly Briefing - {today}"
                    msg["From"] = gmail_address
                    msg["To"] = gmail_address
                    msg.attach(MIMEText(summary, "plain"))
                    msg.attach(MIMEText(html, "html"))

                    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                        server.login(gmail_address, gmail_password.replace(" ", ""))
                        server.sendmail(gmail_address, gmail_address, msg.as_string())

                send_briefing_email(summary, today, len(active_df), weekly_metrics)
                st.success("✅ Briefing emailed to you successfully!")

            except Exception as e:
                st.error(f"❌ Failed to generate briefing: {e}")

    # ── Display persisted briefing (outside button block) ──
    if st.session_state.get("briefing_summary"):
        st.divider()
        st.subheader(f"📋 Weekly Briefing — {st.session_state['briefing_date']}")
        st.markdown(st.session_state["briefing_summary"])
        st.divider()
        st.subheader("📊 Weekly Pipeline Metrics")
        metric_cols = st.columns(3)
        metric_cols[0].metric("Total Active Roles", st.session_state["briefing_active_count"])
        metric_cols[1].metric("Total Applied", int(st.session_state["briefing_metrics"]["Applied"].sum()))
        metric_cols[2].metric("Total Rejected", int(st.session_state["briefing_metrics"]["Rejected"].sum()))
        st.dataframe(
            st.session_state["briefing_metrics"],
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("No briefing generated yet - click the button above to generate one.")

elif page == "⚙️ Settings":
    st.title("⚙️ Settings")
    st.markdown("Configure your job search preferences. These are used when scoring new roles.")

    settings = load_settings()

    with st.form("settings_form"):

        st.subheader("💰 Compensation Targets")
        comp1, comp2, comp3 = st.columns(3)
        with comp1:
            target_base = st.number_input(
                "Target Base Salary ($)",
                value=int(settings["target_base"]),
                step=10000,
                format="%d"
            )
        with comp2:
            target_comp_min = st.number_input(
                "Target Total Comp Min ($)",
                value=int(settings["target_total_comp_min"]),
                step=10000,
                format="%d"
            )
        with comp3:
            target_comp_max = st.number_input(
                "Target Total Comp Max ($)",
                value=int(settings["target_total_comp_max"]),
                step=10000,
                format="%d"
            )

        comp_flex = st.text_input(
            "Compensation Flexibility Note",
            value=settings["comp_flex_note"]
        )

        st.divider()
        st.subheader("📍 Location Preferences")
        locations = st.text_input(
            "Preferred Locations (comma separated)",
            value=settings["locations"]
        )

        st.divider()
        st.subheader("🎯 Target Roles")
        target_roles = st.text_area(
            "Target Role Types",
            value=settings["target_roles"],
            height=150
        )
        exclude_roles = st.text_area(
            "Exclude These Role Types",
            value=settings["exclude_roles"],
            height=80
        )

        st.divider()
        st.subheader("🏢 Company Preferences")
        company_high = st.text_area(
            "High Priority Companies/Sectors",
            value=settings["company_high_priority"],
            height=100
        )
        company_strong = st.text_area(
            "Strong Fit Companies/Sectors",
            value=settings["company_strong_fit"],
            height=100
        )
        company_conditional = st.text_area(
            "Conditional Companies/Sectors",
            value=settings["company_conditional"],
            height=80
        )

        st.divider()
        st.subheader("📊 Scoring Notes")
        scoring_notes = st.text_area(
            "Scoring Criteria Descriptions",
            value=settings["scoring_notes"],
            height=150
        )

        st.divider()
        col1, col2 = st.columns([1, 1])
        with col1:
            saved = st.form_submit_button("💾 Save Settings", use_container_width=True, type="primary")
        with col2:
            reset = st.form_submit_button("🔄 Reset to Defaults", use_container_width=True)

        if saved:
            new_settings = {
                "target_base": target_base,
                "target_total_comp_min": target_comp_min,
                "target_total_comp_max": target_comp_max,
                "comp_flex_note": comp_flex,
                "locations": locations,
                "target_roles": target_roles,
                "exclude_roles": exclude_roles,
                "company_high_priority": company_high,
                "company_strong_fit": company_strong,
                "company_conditional": company_conditional,
                "scoring_notes": scoring_notes
            }
            save_settings(new_settings)
            # Rebuild PREFERENCES globally
            st.session_state["preferences_updated"] = True
            st.success("✅ Settings saved! New roles will be scored with updated preferences.")
            st.rerun()

        if reset:
            save_settings(DEFAULT_SETTINGS)
            st.success("✅ Settings reset to defaults!")
            st.rerun()

    # Show current preferences preview
    with st.expander("👁️ Preview Current Scoring Prompt"):
        st.text(build_preferences(load_settings()))