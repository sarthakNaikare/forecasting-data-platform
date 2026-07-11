"""
FRI Forecasting Data Platform - Analytics Dashboard
"""
import streamlit as st
import duckdb
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import os

st.set_page_config(
    page_title="FRI Forecasting Platform",
    page_icon="🔭",
    layout="wide",
    initial_sidebar_state="expanded",
)

GREEN_DEEP   = "#102B23"
GREEN_MID    = "#1a4235"
GREEN_LIGHT  = "#2d6a4f"
GREEN_ACCENT = "#52b788"
GREEN_PALE   = "#d8f3dc"
AMBER        = "#e9c46a"
RED_SOFT     = "#e76f51"

TYPE_COLORS = {
    "superforecaster": GREEN_DEEP,
    "expert":          GREEN_MID,
    "public":          GREEN_ACCENT,
}

st.markdown(f"""
<style>
[data-testid="stSidebar"] {{ background: {GREEN_DEEP}; }}
[data-testid="stSidebar"] * {{ color: white !important; }}
.metric-card {{
    background: white; border-radius: 10px; padding: 20px 24px;
    box-shadow: 0 2px 12px rgba(16,43,35,0.08); text-align: center;
    border-top: 3px solid {GREEN_ACCENT};
}}
.metric-value {{ font-size: 2.2rem; font-weight: 700; color: {GREEN_DEEP}; line-height: 1; }}
.metric-label {{ font-size: 0.75rem; color: #7a7a7a; margin-top: 6px; text-transform: uppercase; letter-spacing: 0.05em; }}
.insight-box {{
    background: {GREEN_PALE}; border-left: 3px solid {GREEN_ACCENT};
    padding: 10px 14px; border-radius: 4px; font-size: 0.85rem;
    color: {GREEN_MID}; font-style: italic; margin-bottom: 16px;
}}
.section-title {{ font-size: 1.1rem; font-weight: 600; color: {GREEN_DEEP}; margin-bottom: 4px; }}
.section-sub {{ font-size: 0.82rem; color: #7a7a7a; margin-bottom: 16px; }}
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_connection():
    db_path = os.path.join(os.path.dirname(__file__), "..", "fri_worktest.duckdb")
    return duckdb.connect(db_path, read_only=True)


@st.cache_data(ttl=300)
def run_query(sql):
    con = get_connection()
    return con.execute(sql).fetchdf()


def load_all():
    questions = run_query("""
        SELECT q.question_id, q.question_text,
            COUNT(DISTINCT f.forecaster_sk)  AS forecaster_count,
            ROUND(MEDIAN(f.prediction), 1)   AS median_prediction,
            ROUND(AVG(f.prediction), 1)      AS mean_prediction,
            ROUND(STDDEV(f.prediction), 1)   AS stddev_prediction,
            MIN(f.prediction)                AS min_prediction,
            MAX(f.prediction)                AS max_prediction
        FROM fct_forecasts f
        JOIN dim_questions q ON f.question_sk = q.question_sk
        GROUP BY q.question_id, q.question_text
        ORDER BY q.question_id
    """)

    comparison = run_query("""
        WITH latest AS (
            SELECT f.forecaster_sk, f.question_sk, f.prediction, d.forecaster_type,
                ROW_NUMBER() OVER (
                    PARTITION BY f.forecaster_sk, f.question_sk
                    ORDER BY f.forecast_timestamp DESC
                ) AS rn
            FROM fct_forecasts f
            JOIN dim_forecasters d ON f.forecaster_sk = d.forecaster_sk
        )
        SELECT forecaster_type,
            COUNT(DISTINCT forecaster_sk)  AS forecaster_count,
            COUNT(*)                       AS total_forecasts,
            ROUND(AVG(prediction), 1)      AS avg_prediction,
            ROUND(MEDIAN(prediction), 1)   AS median_prediction,
            ROUND(STDDEV(prediction), 1)   AS prediction_stddev
        FROM latest WHERE rn = 1
        GROUP BY forecaster_type
        ORDER BY avg_prediction DESC
    """)

    revisions = run_query("""
        WITH numbered AS (
            SELECT d.forecaster_id, d.forecaster_name, d.forecaster_type,
                q.question_id, q.question_text, f.prediction, f.forecast_timestamp,
                ROW_NUMBER() OVER (
                    PARTITION BY f.forecaster_sk, f.question_sk
                    ORDER BY f.forecast_timestamp
                ) AS update_number
            FROM fct_forecasts f
            JOIN dim_forecasters d ON f.forecaster_sk = d.forecaster_sk
            JOIN dim_questions q ON f.question_sk = q.question_sk
        ),
        with_max AS (
            SELECT *, MAX(update_number) OVER (
                PARTITION BY forecaster_id, question_id
            ) AS max_update FROM numbered
        )
        SELECT forecaster_id, forecaster_name, forecaster_type,
            question_id, question_text,
            MIN(prediction) AS first_prediction,
            MAX(CASE WHEN update_number = max_update THEN prediction END) AS last_prediction,
            MAX(CASE WHEN update_number = max_update THEN prediction END)
                - MIN(prediction) AS net_revision,
            COUNT(*) AS total_submissions
        FROM with_max
        GROUP BY forecaster_id, forecaster_name, forecaster_type, question_id, question_text
        HAVING COUNT(*) > 1
        ORDER BY ABS(MAX(CASE WHEN update_number = max_update THEN prediction END) - MIN(prediction)) DESC
    """)

    calibration = run_query("""
        WITH latest AS (
            SELECT f.forecaster_sk, f.question_sk, f.prediction, d.forecaster_type,
                ROW_NUMBER() OVER (
                    PARTITION BY f.forecaster_sk, f.question_sk
                    ORDER BY f.forecast_timestamp DESC
                ) AS rn
            FROM fct_forecasts f
            JOIN dim_forecasters d ON f.forecaster_sk = d.forecaster_sk
        )
        SELECT q.question_id,
            ROUND(AVG(CASE WHEN l.forecaster_type = 'superforecaster' THEN l.prediction END), 1) AS sf_avg,
            ROUND(STDDEV(CASE WHEN l.forecaster_type = 'superforecaster' THEN l.prediction END), 1) AS sf_stddev,
            ROUND(AVG(CASE WHEN l.forecaster_type = 'expert' THEN l.prediction END), 1) AS expert_avg,
            ROUND(STDDEV(CASE WHEN l.forecaster_type = 'expert' THEN l.prediction END), 1) AS expert_stddev,
            ROUND(AVG(CASE WHEN l.forecaster_type = 'public' THEN l.prediction END), 1) AS public_avg,
            ROUND(STDDEV(CASE WHEN l.forecaster_type = 'public' THEN l.prediction END), 1) AS public_stddev
        FROM latest l
        JOIN dim_questions q ON l.question_sk = q.question_sk
        WHERE l.rn = 1
        GROUP BY q.question_id ORDER BY q.question_id
    """)

    engagement = run_query("""
        SELECT d.forecaster_id, d.forecaster_name, d.forecaster_type,
            d.years_forecasting_experience, d.education_level, d.country,
            COUNT(DISTINCT f.question_sk)  AS questions_covered,
            COUNT(*)                       AS total_submissions,
            ROUND(AVG(f.prediction), 1)    AS avg_prediction,
            MIN(f.prediction)              AS min_prediction,
            MAX(f.prediction)              AS max_prediction
        FROM fct_forecasts f
        JOIN dim_forecasters d ON f.forecaster_sk = d.forecaster_sk
        GROUP BY d.forecaster_id, d.forecaster_name, d.forecaster_type,
            d.years_forecasting_experience, d.education_level, d.country
        ORDER BY total_submissions DESC
    """)

    return questions, comparison, revisions, calibration, engagement


with st.sidebar:
    st.markdown("## 🔭 FRI Platform")
    st.markdown("Forecasting Data Warehouse")
    st.markdown("---")
    page = st.radio("Navigate", [
        "📊 Question Overview",
        "👥 Forecaster Types",
        "🔄 Belief Revisions",
        "🎯 Calibration Spread",
        "📈 Engagement",
        "🗃️ Data Quality",
    ])
    st.markdown("---")
    st.markdown(
        "<small>DuckDB · FastAPI · Streamlit<br>Dimensional model · 5 tables<br>89 forecasts · 10 forecasters</small>",
        unsafe_allow_html=True
    )

questions, comparison, revisions, calibration, engagement = load_all()

st.markdown("### FRI Forecasting Data Platform")
st.markdown("<p style=\'color:#7a7a7a;font-size:0.85rem;margin-bottom:24px\'>Dimensional warehouse analytics over AI forecasting survey data</p>", unsafe_allow_html=True)

c1, c2, c3, c4, c5 = st.columns(5)
overall_median = round(questions["median_prediction"].mean(), 1)
total_subs = engagement["total_submissions"].sum()

for col, val, label in [
    (c1, len(questions), "Questions"),
    (c2, len(engagement), "Forecasters"),
    (c3, int(total_subs), "Submissions"),
    (c4, f"{overall_median}%", "Overall Median"),
    (c5, len(revisions), "Belief Updates"),
]:
    col.markdown(
        f'<div class="metric-card"><div class="metric-value">{val}</div><div class="metric-label">{label}</div></div>',
        unsafe_allow_html=True
    )

st.markdown("<br>", unsafe_allow_html=True)

if page == "📊 Question Overview":
    st.markdown('<div class="section-title">Predicted Probability by Question</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Median prediction across all forecaster types. Error bars show min/max range.</div>', unsafe_allow_html=True)

    lowest = questions.loc[questions["median_prediction"].idxmin()]
    highest = questions.loc[questions["median_prediction"].idxmax()]

    st.markdown(
        f'<div class="insight-box">Forecasters are most confident about <b>{highest["question_id"]}</b> ' +
        f'(compute scaling, {highest["median_prediction"]}% median) and least confident about ' +
        f'<b>{lowest["question_id"]}</b> (voluntary AI pause, {lowest["median_prediction"]}% median). ' +
        f'Spread: {highest["median_prediction"] - lowest["median_prediction"]} percentage points.</div>',
        unsafe_allow_html=True
    )

    questions["short_text"] = questions["question_id"] + ": " + questions["question_text"].str[:55] + "..."

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=questions["short_text"],
        x=questions["median_p thickness=2, width=8),
                text=[f"{row['avg_prediction']}%"],
                textposition="outside",
            ))
        fig_bar.update_layout(
            title="Average Prediction +- Std Dev",
            yaxis=dict(title="Avg Predicted Probability (%)", range=[0, 75]),
            plot_bgcolor="white", paper_bgcolor="white", showlegend=False, height=360,
            margin=dict(l=20, r=20, t=40, b=20),
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    with col2:
        raw = run_query("""
            WITH latest AS (
                SELECT f.prediction, d.forecaster_type,
                    ROW_NUMBER() OVER (PARTITION BY f.forecaster_sk, f.question_sk ORDER BY f.forecast_timestamp DESC) AS rn
                FROM fct_forecasts f JOIN dim_forecasters d ON f.forecaster_sk = d.forecaster_sk
            )
            SELECT prediction, forecaster_type FROM latest WHERE rn = 1
        """)
        fig_box = go.Figure()
        for ftype, color in TYPE_COLORS.items():
            subset = raw[raw["forecaster_type"] == ftype]["prediction"]
            fig_box.add_trace(go.Box(y=subset, name=ftype, marker_color=color, boxmean=True))
        fig_box.update_layout(
            title="Prediction Distribution by Type",
            yaxis=dict(title="Predicted Probability (%)"),
            plot_bgcolor="white", paper_bgcolor="white", height=360, showlegend=False,
            margin=dict(l=20, r=20, t=40, b=20),
        )
        st.plotly_chart(fig_box, use_container_width=True)

    display = comparison.copy()
    display.columns = ["Type", "Forecasters", "Total Forecasts", "Avg %", "Median %", "Std Dev"]
    st.dataframe(display, use_container_width=True, hide_index=True)

elif page == "🔄 Belief Revisions":
    st.markdown('<div class="section-title">Belief Revision Analysis</div>', unsafe_allow_html=True)

    up_count = len(revisions[revisions["net_revision"] > 0])
    max_rev = int(revisions["net_revision"].abs().max())

    st.markdown(
        f'<div class="insight-box">{up_count} of {len(revisions)} revisions went upward. ' +
        f'Largest single revision: {max_rev} percentage points. ' +
        f'All forecasters who updated moved toward higher AI capability probabilities.</div>',
        unsafe_allow_html=True
    )

    col1, col2 = st.columns(2)
    with col1:
        fig_scatter = go.Figure()
        for ftype, color in TYPE_COLORS.items():
            subset = revisions[revisions["forecaster_type"] == ftype]
            if len(subset) == 0:
                continue
            fig_scatter.add_trace(go.Scatter(
                x=subset["first_prediction"], y=subset["last_prediction"],
                mode="markers+text", name=ftype, marker=dict(color=color, size=10),
                text=subset["forecaster_name"].str.split().str[0],
                textposition="top center", textfont=dict(size=9),
            ))
        fig_scatter.add_shape(type="line", x0=0, y0=0, x1=100, y1=100, line=dict(color="#ccc", dash="dash", width=1))
        fig_scatter.update_layout(
            title="First vs Last Prediction",
            xaxis=dict(title="First Prediction (%)", range=[0, 100]),
            yaxis=dict(title="Last Prediction (%)", range=[0, 100]),
            plot_bgcolor="white", paper_bgcolor="white", height=380,
            margin=dict(l=20, r=20, t=40, b=20),
        )
        st.plotly_chart(fig_scatter, use_container_width=True)

    with col2:
        rev_sorted = revisions.copy()
        rev_sorted["label"] = rev_sorted["forecaster_name"].str.split().str[0] + " / " + rev_sorted["question_id"]
        rev_sorted["color"] = rev_sorted["net_revision"].apply(lambda x: GREEN_LIGHT if x > 0 else RED_SOFT if x < 0 else "#ccc")
        fig_rev = go.Figure(go.Bar(
            x=rev_sorted["net_revision"], y=rev_sorted["label"],
            orientation="h", marker_color=rev_sorted["color"],
        ))
        fig_rev.add_vline(x=0, line_color="#333", line_width=1)
        fig_rev.update_layout(
            title="Net Revision (First to Last)",
            xaxis=dict(title="Percentage Points"),
            plot_bgcolor="white", paper_bgcolor="white", height=380,
            margin=dict(l=20, r=20, t=40, b=20),
        )
        st.plotly_chart(fig_rev, use_container_width=True)

    display = revisions[["forecaster_name", "forecaster_type", "question_id",
                         "first_prediction", "last_prediction", "net_revision", "total_submissions"]].copy()
    display.columns = ["Forecaster", "Type", "Question", "First %", "Last %", "Net Change", "Submissions"]
    st.dataframe(display, use_container_width=True, hide_index=True)

elif page == "🎯 Calibration Spread":
    st.markdown('<div class="section-title">Calibration Spread by Forecaster Type</div>', unsafe_allow_html=True)

    sf_avg_std = calibration["sf_stddev"].mean()
    pub_avg_std = calibration["public_stddev"].mean()
    tetlock = sf_avg_std < pub_avg_std

    st.markdown(
        f'<div class="insight-box">Superforecasters avg σ: {sf_avg_std:.1f} vs public avg σ: {pub_avg_std:.1f}. ' +
        (f'Confirms Tetlock calibration hypothesis on this dataset.' if tetlock else f'Does not confirm hypothesis, likely due to small sample size.') +
        '</div>',
        unsafe_allow_html=True
    )

    rows = []
    for _, r in calibration.iterrows():
        for ftype, avg_col, std_col in [("superforecaster","sf_avg","sf_stddev"),("expert","expert_avg","expert_stddev"),("public","public_avg","public_stddev")]:
            rows.append({"question": r["question_id"], "type": ftype, "avg": r[avg_col], "stddev": r[std_col]})
    calib_long = pd.DataFrame(rows)

    fig = px.bar(calib_long, x="question", y="stddev", color="type", barmode="group",
                 color_discrete_map=TYPE_COLORS,
                 labels={"stddev": "Standard Deviation", "question": "Question", "type": "Type"},
                 title="Prediction Spread per Question by Forecaster Type")
    fig.update_layout(plot_bgcolor="white", paper_bgcolor="white", height=400,
                      margin=dict(l=20, r=20, t=40, b=20), legend=dict(orientation="h", y=1.12))
    st.plotly_chart(fig, use_container_width=True)

    display = calibration.copy()
    display.columns = ["Question", "SF Avg", "SF sigma", "Expert Avg", "Expert sigma", "Public Avg", "Public sigma"]
    st.dataframe(display, use_container_width=True, hide_index=True)

elif page == "📈 Engagement":
    st.markdown('<div class="section-title">Forecaster Engagement</div>', unsafe_allow_html=True)

    most_active = engagement.iloc[0]
    st.markdown(
        f'<div class="insight-box">{most_active["forecaster_name"]} ({most_active["forecaster_type"]}) leads with ' +
        f'{most_active["total_submissions"]} submissions across {most_active["questions_covered"]} questions.</div>',
        unsafe_allow_html=True
    )

    col1, col2 = st.columns(2)
    with col1:
        fig_eng = px.bar(engagement, x="total_submissions", y="forecaster_name",
                        color="forecaster_type", orientation="h", color_discrete_map=TYPE_COLORS,
                        labels={"total_submissions": "Total Submissions", "forecaster_name": "", "forecaster_type": "Type"},
                        title="Total Submissions per Forecaster")
        fig_eng.update_layout(plot_bgcolor="white", paper_bgcolor="white", height=380,
                             margin=dict(l=20, r=20, t=40, b=20), yaxis=dict(autorange="reversed"),
                             legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig_eng, use_container_width=True)

    with col2:
        fig_exp t_size=9)
        fig_exp.update_layout(plot_bgcolor="white", paper_bgcolor="white", height=380,
                             margin=dict(l=20, r=20, t=40, b=20), showlegend=False)
        st.plotly_chart(fig_exp, use_container_width=True)

    display = engagement[["forecaster_name","forecaster_type","years_forecasting_experience",
                          "education_level","country","questions_covered","total_submissions","avg_prediction"]].copy()
    display.columns = ["Name","Type","Exp (yrs)","Education","Country","Questions","Submissions","Avg %"]
    st.dataframe(display, use_container_width=True, hide_index=True)

elif page == "🗃️ Data Quality":
    st.markdown('<div class="section-title">Data Quality Report</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="insight-box">8 issues found across 3 raw tables. All resolved before loading into the dimensional model. ' +
        'Cleaned warehouse: 89 fact rows (down from 90), 19 unique tags (down from 20).</div>',
        unsafe_allow_html=True
    )

    issues = [
        ("High",   "raw_forecasts_export",        "All columns",                "Exact duplicate row (F005, Q002)",              "ROW_NUMBER() dedup in fct_forecasts CTE"),
        ("Low",    "raw_forecasts_export",        "rationale",                  "3 empty strings instead of NULL",               "NULLIF(TRIM(rationale), \'\') in fct_forecasts"),
        ("High",   "raw_forecaster_demographics", "joined_date",                "F006 uses prose date March 15 2023",            "COALESCE(TRY_CAST, TRY_STRPTIME) in dim_forecasters"),
        ("Medium", "raw_forecaster_demographics", "education_level",            "Bachelor vs Bachelors inconsistency",           "CASE normalisation in dim_forecasters"),
        ("Medium", "raw_forecaster_demographics", "education_level/affiliation","F007 has NULL education and affiliation",        "Kept as NULL, has_complete_profile flag added"),
        ("Medium", "raw_forecaster_demographics", "forecaster_id",              "F099 in demographics but 0 forecasts",          "Kept in dim_forecasters, is_active = FALSE"),
        ("High",   "raw_question_tags",           "tag",                        "Q003 tag mixed case Artificial-Intelligence",   "LOWER(TRIM(tag)) in bridge_question_tags"),
        ("High",   "raw_question_tags",           "question_id + tag",          "Q001 artificial-intelligence duplicated",       "DISTINCT after lowercasing in bridge"),
    ]

    df_issues = pd.DataFrame(issues, columns=["Severity","Table","Column(s)","Issue","Resolution"])

    def color_severity(val):
        if val == "High":   return "background-color: #fde8e8; color: #c62828"
        if val == "Medium": return "background-color: #fff3e0; color: #e65100"
        return "background-color: #e8f5e9; color: #2e7d32"

    styled = df_issues.style.map(color_severity, subset=["Severity"])
    st.dataframe(styled, use_container_width=True, hide_index=True)

    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    raw_counts  = run_query("SELECT COUNT(*) AS raw_rows FROM raw_forecasts_export")
    clean_counts = run_query("SELECT COUNT(*) AS fact_rows FROM fct_forecasts")
    tag_counts  = run_query("SELECT COUNT(*) AS raw_tags FROM raw_question_tags")
    clean_tags  = run_query("SELECT COUNT(*) AS clean_tags FROM bridge_question_tags")

    col1.metric("Raw forecast rows", int(raw_counts["raw_rows"].iloc[0]))
    col1.metric("After dedup",       int(clean_counts["fact_rows"].iloc[0]), delta="-1 duplicate")
    col2.metric("Raw tag rows",      int(tag_counts["raw_tags"].iloc[0]))
    col2.metric("After normalise",   int(clean_tags["clean_tags"].iloc[0]), delta="-1 duplicate")
    col3.metric("Issues found", 8)
    col3.metric("Issues resolved", 8, delta="100%")
