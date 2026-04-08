import streamlit as st
import os
import json
import requests
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

def score_role(job_description, manual_glassdoor="", manual_ceo=""):

    # -- PASS 1: Full scoring first using complete JD --
    prompt = f"""
You are an expert career advisor evaluating a job opportunity for a senior technology executive.

CANDIDATE RESUME:
{RESUME}

CANDIDATE PREFERENCES & SCORING CRITERIA:
{PREFERENCES}

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
  "current_status": "Not Applied",
  "date_added": "{datetime.today().strftime('%m/%d/%Y')}"
}}
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are an expert career advisor. Return only valid JSON."},
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

    # Apply manual overrides if provided
    if manual_glassdoor.strip():
        scored["glassdoor_rating"] = manual_glassdoor.strip()
    if manual_ceo.strip():
        scored["ceo_approval"] = manual_ceo.strip()

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
        "Current Status": scored.get("current_status", "Not Applied"),
        "Date Added to Tracker": scored.get("date_added", ""),
        "Application Link": job_url,
    }

    new_row = [column_map.get(h, "") for h in headers]
    worksheet.append_row(new_row, value_input_option="USER_ENTERED")

# ─────────────────────────────────────────
# STREAMLIT UI
# ─────────────────────────────────────────

st.set_page_config(page_title="Job Role Scorer", page_icon="🎯", layout="wide")

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

st.title("🎯 Job Role Scorer")
st.markdown("Paste a job description to score it against your resume and preferences.")

# Input form
with st.form("scorer_form"):
    job_url = st.text_input(
        "Job URL (optional - for reference only)",
        placeholder="https://jobs.ashbyhq.com/company/job-id"
    )
    job_description = st.text_area(
        "Paste Job Description",
        height=300,
        placeholder="Paste the full job description here..."
    )

    st.markdown("**Optional - Manual Glassdoor Override**")
    st.caption("Fill these in if you already know them - overrides the auto-lookup")
    ov1, ov2 = st.columns(2)
    with ov1:
        manual_glassdoor = st.text_input("Glassdoor Rating", placeholder="e.g. 4.0")
    with ov2:
        manual_ceo = st.text_input("CEO Approval %", placeholder="e.g. 78%")

    submitted = st.form_submit_button("🔍 Score This Role", use_container_width=True)

# Score the role
if submitted:
    if not job_description.strip():
        st.error("Please paste a job description.")
    else:
        with st.spinner("Scoring role - looking up Glassdoor, Blind, and running analysis..."):
            try:
                scored, company_name, glassdoor_data, blind_data = score_role(
                    job_description,
                    manual_glassdoor,
                    manual_ceo
                )

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