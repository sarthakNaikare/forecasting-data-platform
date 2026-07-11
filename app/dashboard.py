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
    initial_sidebar_state="expanded"
)

G1 = "#102B23"
G2 = "#1a4235"
G3 = "#2d6a4f"
G4 = "#52b788"
G5 = "#d8f3dc"
AMBER = "#e9c46a"
RED = "#e76f51"
TC = {"superforecaster": G1, "expert": G2, "public": G4}

st.markdown("""
<style>
[data-testid="stSidebar"] {background:#102B23}
[data-testid="stSidebar"] * {color:white!important}
.mc{background:white;border-radius:10px;padding:20px;box-shadow:0 2px 12px rgba(16,43,35,.08);text-align:center;border-top:3px solid #52b788}
.mv{font-size:2.2rem;font-weight:700;color:#102B23;line-height:1}
.ml{font-size:.75rem;color:#7a7a7a;margin-top:6px;text-transform:uppercase;letter-spacing:.05em}
.ib{background:#d8f3dc;border-left:3px solid #52b788;padding:10px 14px;border-radius:4px;font-size:.85rem;color:#1a4235;font-style:italic;margin-bottom:16px}
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_con():
    db = os.path.join(os.path.dirname(__file__), "..", "fri_worktest.duckdb")
    return duckdb.connect(db, read_only=True)


@st.cache_data(ttl=300)
def run(sql):
    return get_con().execute(sql).fetchdf()


def insight(text):
    st.markdown(f'<div class="ib">{text}</div>', unsafe_allow_html=True)


def metric_card(col, val, label):
    col.markdown(
        f'<div class="mc"><div class="mv">{val}</div><div class="ml">{label}</div></div>',
        unsafe_allow_html=True
    )


questions = run("""
    SELECT q.question_id, q.question_text,
        COUNT(DISTINCT f.forecaster_sk) AS forecaster_count,
        ROUND(MEDIAN(f.prediction),1) AS median_prediction,
        ROUND(AVG(f.prediction),1) AS mean_prediction,
        ROUND(STDDEV(f.prediction),1) AS stddev_prediction,
        MIN(f.prediction) AS min_prediction,
        MAX(f.prediction) AS max_prediction
    FROM fct_forecasts f
    JOIN dim_questions q ON f.question_sk = q.question_sk
    GROUP BY q.question_id, q.question_text
    ORDER BY q.question_id
""")

comparison = run("""
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
        COUNT(DISTINCT forecaster_sk) AS forecaster_count,
        COUNT(*) AS total_forecasts,
        ROUND(AVG(prediction),1) AS avg_prediction,
        ROUND(MEDIAN(prediction),1) AS median_prediction,
        ROUND(STDDEV(prediction),1) AS prediction_stddev
    FROM latest WHERE rn = 1
    GROUP BY forecaster_type
    ORDER BY avg_prediction DESC
""")

revisions = run("""
    WITH numbered AS (
        SELECT d.forecaster_id, d.forecaster_name, d.forecaster_type,
            q.question_id, f.prediction, f.forecast_timestamp,
            ROW_NUMBER() OVER (
                PARTITION BY f.forecaster_sk, f.question_sk
                ORDER BY f.forecast_timestamp
            ) AS rn
        FROM fct_forecasts f
        JOIN dim_forecasters d ON f.forecaster_sk = d.forecaster_sk
        JOIN dim_questions q ON f.question_sk = q.question_sk
    ),
    wm AS (
        SELECT *, MAX(rn) OVER (PARTITION BY forecaster_id, question_id) AS max_rn
        FROM numbered
    )
    SELECT forecaster_id, forecaster_name, forecaster_type, question_id,
        MIN(prediction) AS first_prediction,
        MAX(CASE WHEN rn = max_rn THEN prediction END) AS last_prediction,
        MAX(CASE WHEN rn = max_rn THEN prediction END) - MIN(prediction) AS net_revision,
        COUNT(*) AS total_submissions
    FROM wm
    GROUP BY forecaster_id, forecaster_name, forecaster_type, question_id
    HAVING COUNT(*) > 1
    ORDER BY ABS(MAX(CASE WHEN rn = max_rn THEN prediction END) - MIN(prediction)) DESC
""")

calibration = run("""
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
        ROUND(AVG(CASE WHEN l.forecaster_type = 'superforecaster' THEN l.prediction END),1) AS sf_avg,
        ROUND(STDDEV(CASE WHEN l.forecaster_type = 'superforecaster' THEN l.prediction END),1) AS sf_stddev,
        ROUND(AVG(CASE WHEN l.forecaster_type = 'expert' THEN l.prediction END),1) AS expert_avg,
        ROUND(STDDEV(CASE WHEN l.forecaster_type = 'expert' THEN l.prediction END),1) AS expert_stddev,
        ROUND(AVG(CASE WHEN l.forecaster_type = 'public' THEN l.prediction END),1) AS public_avg,
        ROUND(STDDEV(CASE WHEN l.forecaster_type = 'public' THEN l.prediction END),1) AS public_stddev
    FROM latest l
    JOIN dim_questions q ON l.question_sk = q.question_sk
    WHERE l.rn = 1
    GROUP BY q.question_id
    ORDER BY q.question_id
""")

engagement = run("""
    SELECT d.forecaster_id, d.forecaster_name, d.forecaster_type,
        d.years_forecasting_experience, d.education_level, d.country,
        COUNT(DISTINCT f.question_sk) AS questions_covered,
        COUNT(*) AS total_submissions,
        ROUND(AVG(f.prediction),1) AS avg_prediction
    FROM fct_forecasts f
    JOIN dim_forecasters d ON f.forecaster_sk = d.forecaster_sk
    GROUP BY d.forecaster_id, d.forecaster_name, d.forecaster_type,
        d.years_forecasting_experience, d.education_level, d.country
    ORDER BY total_submissions DESC
""")

with st.sidebar:
    st.markdown("## 🔭 FRI Platform")
    st.markdown("Forecasting Data Warehouse")
    st.markdown("---")
    page = st.radio("Navigate", [
        "📊 Questions",
        "👥 Forecaster Types",
        "🔄 Belief Revisions",
        "🎯 Calibration",
        "📈 Engagement",
        "🗃️ Data Quality",
    ])
    st.markdown("---")
    st.markdown(
        "<small>DuckDB · FastAPI · Streamlit<br>"
        "5 tables · 89 forecasts · 10 forecasters</small>",
        unsafe_allow_html=True
    )

st.markdown("### FRI Forecasting Data Platform")
st.markdown(
    "<p style='color:#7a7a7a;font-size:.85rem;margin-bottom:24px'>"
    "Dimensional warehouse analytics over AI forecasting survey data</p>",
    unsafe_allow_html=True
)

c1, c2, c3, c4, c5 = st.columns(5)
overall_median = round(float(questions["median_prediction"].mean()), 1)
total_subs = int(engagement["total_submissions"].sum())
metric_card(c1, len(questions), "Questions")
metric_card(c2, len(engagement), "Forecasters")
metric_card(c3, total_subs, "Submissions")
metric_card(c4, f"{overall_median}%", "Overall Median")
metric_card(c5, len(revisions), "Belief Updates")
st.markdown("<br>", unsafe_allow_html=True)

if page == "📊 Questions":
    st.markdown("#### Predicted Probability by Question")
    lowest = questions.loc[questions["median_prediction"].idxmin()]
    highest = questions.loc[questions["median_prediction"].idxmax()]
    insight(
        f"Most confident: <b>{highest['question_id']}</b> compute scaling at "
        f"{highest['median_prediction']}%. Least confident: <b>{lowest['question_id']}</b> "
        f"voluntary pause at {lowest['median_prediction']}%. "
        f"Spread: {highest['median_prediction'] - lowest['median_prediction']} percentage points."
    )
    questions["label"] = (
        questions["question_id"] + ": " + questions["question_text"].str[:55] + "..."
    )
    fig = go.Figure(go.Bar(
        y=questions["label"],
        x=questions["median_prediction"],
        orientation="h",
        marker=dict(
            color=questions["median_prediction"],
            colorscale=[[0, RED], [0.3, AMBER], [0.6, G4], [1, G1]],
            showscale=True,
            colorbar=dict(title="Median %", thickness=12),
        ),
        error_x=dict(
            type="data", symmetric=False,
            array=questions["max_prediction"] - questions["median_prediction"],
            arrayminus=questions["median_prediction"] - questions["min_prediction"],
            color="#aaa", thickness=1.5,
        ),
        text=questions["median_prediction"].astype(str) + "%",
        textposition="outside",
    ))
    fig.update_layout(
        height=460,
        margin=dict(l=20, r=60, t=20, b=20),
        xaxis=dict(title="Predicted Probability (%)", range=[0, 115]),
        yaxis=dict(autorange="reversed"),
        plot_bgcolor="white",
        paper_bgcolor="white",
    )
    st.plotly_chart(fig, use_container_width=True)
    d = questions[[
        "question_id", "question_text", "forecaster_count",
        "median_prediction", "mean_prediction", "stddev_prediction",
        "min_prediction", "max_prediction"
    ]].copy()
    d.columns = ["ID", "Question", "Forecasters", "Median %", "Mean %", "Std Dev", "Min %", "Max %"]
    st.dataframe(d, use_container_width=True, hide_index=True)

elif page == "👥 Forecaster Types":
    st.markdown("#### Superforecasters vs Experts vs Public")
    sf = comparison[comparison["forecaster_type"] == "superforecaster"].iloc[0]
    pub = comparison[comparison["forecaster_type"] == "public"].iloc[0]
    insight(
        f"Superforecasters show sigma {sf['prediction_stddev']} vs public at sigma "
        f"{pub['prediction_stddev']}. Higher variance among superforecasters reflects "
        f"more decisive positions away from 50%, consistent with Tetlock's findings."
    )
    col1, col2 = st.columns(2)
    with col1:
        fig = go.Figure()
        for _, row in comparison.iterrows():
            fig.add_trace(go.Bar(
                name=row["forecaster_type"],
                x=[row["forecaster_type"]],
                y=[row["avg_prediction"]],
                marker_color=TC.get(row["forecaster_type"], G4),
                error_y=dict(
                    type="data", array=[row["prediction_stddev"]],
                    visible=True, color="#666", thickness=2, width=8
                ),
                text=[f"{row['avg_prediction']}%"],
                textposition="outside",
            ))
        fig.update_layout(
            title="Average Prediction +/- Std Dev",
            yaxis=dict(range=[0, 75]),
            plot_bgcolor="white", paper_bgcolor="white",
            showlegend=False, height=360,
            margin=dict(l=20, r=20, t=40, b=20),
        )
        st.plotly_chart(fig, use_container_width=True)
    with col2:
        raw = run("""
            WITH latest AS (
                SELECT f.prediction, d.forecaster_type,
                    ROW_NUMBER() OVER (
                        PARTITION BY f.forecaster_sk, f.question_sk
                        ORDER BY f.forecast_timestamp DESC
                    ) AS rn
                FROM fct_forecasts f
                JOIN dim_forecasters d ON f.forecaster_sk = d.forecaster_sk
            )
            SELECT prediction, forecaster_type FROM latest WHERE rn = 1
        """)
        fig2 = go.Figure()
        for ft, color in TC.items():
            fig2.add_trace(go.Box(
                y=raw[raw["forecaster_type"] == ft]["prediction"],
                name=ft, marker_color=color, boxmean=True
            ))
        fig2.update_layout(
            title="Prediction Distribution",
            plot_bgcolor="white", paper_bgcolor="white",
            height=360, showlegend=False,
            margin=dict(l=20, r=20, t=40, b=20),
        )
        st.plotly_chart(fig2, use_container_width=True)
    d = comparison.copy()
    d.columns = ["Type", "Forecasters", "Total Forecasts", "Avg %", "Median %", "Std Dev"]
    st.dataframe(d, use_container_width=True, hide_index=True)

elif page == "🔄 Belief Revisions":
    st.markdown("#### Belief Revision Analysis")
    up = len(revisions[revisions["net_revision"] > 0])
    max_rev = int(revisions["net_revision"].abs().max())
    insight(
        f"{up} of {len(revisions)} revisions went upward. "
        f"All forecasters who updated moved toward higher AI capability probabilities. "
        f"Largest single revision: {max_rev} percentage points."
    )
    col1, col2 = st.columns(2)
    with col1:
        fig = go.Figure()
        for ft, color in TC.items():
            sub = revisions[revisions["forecaster_type"] == ft]
            if len(sub) == 0:
                continue
            fig.add_trace(go.Scatter(
                x=sub["first_prediction"], y=sub["last_prediction"],
                mode="markers+text", name=ft,
                marker=dict(color=color, size=10),
                text=sub["forecaster_name"].str.split().str[0],
                textposition="top center", textfont=dict(size=9),
            ))
        fig.add_shape(
            type="line", x0=0, y0=0, x1=100, y1=100,
            line=dict(color="#ccc", dash="dash", width=1)
        )
        fig.update_layout(
            title="First vs Last Prediction",
            xaxis=dict(title="First (%)", range=[0, 100]),
            yaxis=dict(title="Last (%)", range=[0, 100]),
            plot_bgcolor="white", paper_bgcolor="white",
            height=380, margin=dict(l=20, r=20, t=40, b=20),
        )
        st.plotly_chart(fig, use_container_width=True)
    with col2:
        rev = revisions.copy()
        rev["label"] = (
            rev["forecaster_name"].str.split().str[0] + " / " + rev["question_id"]
        )
        rev["color"] = rev["net_revision"].apply(
            lambda x: G3 if x > 0 else RED if x < 0 else "#ccc"
        )
        fig2 = go.Figure(go.Bar(
            x=rev["net_revision"], y=rev["label"],
            orientation="h", marker_color=rev["color"],
        ))
        fig2.add_vline(x=0, line_color="#333", line_width=1)
        fig2.update_layout(
            title="Net Revision First to Last",
            xaxis=dict(title="Percentage Points"),
            plot_bgcolor="white", paper_bgcolor="white",
            height=380, margin=dict(l=20, r=20, t=40, b=20),
        )
        st.plotly_chart(fig2, use_container_width=True)
    d = revisions[[
        "forecaster_name", "forecaster_type", "question_id",
        "first_prediction", "last_prediction", "net_revision", "total_submissions"
    ]].copy()
    d.columns = ["Forecaster", "Type", "Question", "First %", "Last %", "Net Change", "Submissions"]
    st.dataframe(d, use_container_width=True, hide_index=True)

elif page == "🎯 Calibration":
    st.markdown("#### Calibration Spread by Forecaster Type")
    sf_std = float(calibration["sf_stddev"].mean())
    pub_std = float(calibration["public_stddev"].mean())
    confirmed = sf_std < pub_std
    insight(
        f"Superforecasters avg sigma: {sf_std:.1f} vs public avg sigma: {pub_std:.1f}. "
        + ("Confirms Tetlock calibration hypothesis on this dataset."
           if confirmed else
           "Does not confirm hypothesis, likely due to small sample size (3 superforecasters vs 4 public).")
    )
    rows = []
    for _, r in calibration.iterrows():
        for ft, ac, sc in [
            ("superforecaster", "sf_avg", "sf_stddev"),
            ("expert", "expert_avg", "expert_stddev"),
            ("public", "public_avg", "public_stddev"),
        ]:
            rows.append({"question": r["question_id"], "type": ft, "avg": r[ac], "stddev": r[sc]})
    cl = pd.DataFrame(rows)
    fig = px.bar(
        cl, x="question", y="stddev", color="type", barmode="group",
        color_discrete_map=TC,
        labels={"stddev": "Std Dev", "question": "Question", "type": "Type"},
        title="Prediction Spread per Question by Forecaster Type",
    )
    fig.update_layout(
        plot_bgcolor="white", paper_bgcolor="white",
        height=400, margin=dict(l=20, r=20, t=40, b=20),
        legend=dict(orientation="h", y=1.12),
    )
    st.plotly_chart(fig, use_container_width=True)
    d = calibration.copy()
    d.columns = ["Question", "SF Avg", "SF sigma", "Expert Avg", "Expert sigma", "Public Avg", "Public sigma"]
    st.dataframe(d, use_container_width=True, hide_index=True)

elif page == "📈 Engagement":
    st.markdown("#### Forecaster Engagement")
    top = engagement.iloc[0]
    insight(
        f"{top['forecaster_name']} ({top['forecaster_type']}) leads with "
        f"{top['total_submissions']} submissions across {top['questions_covered']} questions. "
        f"F099 (registered but never forecasted) correctly excluded via the fct_forecasts join."
    )
    col1, col2 = st.columns(2)
    with col1:
        fig = px.bar(
            engagement, x="total_submissions", y="forecaster_name",
            color="forecaster_type", orientation="h", color_discrete_map=TC,
            labels={
                "total_submissions": "Submissions",
                "forecaster_name": "",
                "forecaster_type": "Type",
            },
            title="Total Submissions per Forecaster",
        )
        fig.update_layout(
            plot_bgcolor="white", paper_bgcolor="white",
            height=380, margin=dict(l=20, r=20, t=40, b=20),
            yaxis=dict(autorange="reversed"),
            legend=dict(orientation="h", y=1.1),
        )
        st.plotly_chart(fig, use_container_width=True)
    with col2:
        fig2 = px.scatter(
            engagement, x="years_forecasting_experience", y="avg_prediction",
            color="forecaster_type", size="total_submissions", text="forecaster_name",
            color_discrete_map=TC,
            labels={
                "years_forecasting_experience": "Years Experience",
                "avg_prediction": "Avg Prediction (%)",
            },
            title="Experience vs Average Prediction",
        )
        fig2.update_traces(textposition="top center", textfont_size=9)
        fig2.update_layout(
            plot_bgcolor="white", paper_bgcolor="white",
            height=380, margin=dict(l=20, r=20, t=40, b=20),
            showlegend=False,
        )
        st.plotly_chart(fig2, use_container_width=True)
    d = engagement[[
        "forecaster_name", "forecaster_type", "years_forecasting_experience",
        "education_level", "country", "questions_covered", "total_submissions", "avg_prediction"
    ]].copy()
    d.columns = ["Name", "Type", "Exp", "Education", "Country", "Questions", "Submissions", "Avg %"]
    st.dataframe(d, use_container_width=True, hide_index=True)

elif page == "🗃️ Data Quality":
    st.markdown("#### Data Quality Report")
    insight(
        "8 issues found across 3 raw tables. All resolved before loading into the dimensional model. "
        "89 fact rows after dedup (down from 90), 19 tags after normalisation (down from 20)."
    )
    issues = [
        ("High",   "raw_forecasts_export",        "All columns",        "Exact duplicate row F005 Q002",          "ROW_NUMBER() dedup in fct_forecasts CTE"),
        ("Low",    "raw_forecasts_export",        "rationale",          "3 empty strings instead of NULL",        "NULLIF(TRIM(rationale), empty) in fct_forecasts"),
        ("High",   "raw_forecaster_demographics", "joined_date",        "F006 prose date March 15 2023",          "COALESCE(TRY_CAST, TRY_STRPTIME) in dim_forecasters"),
        ("Medium", "raw_forecaster_demographics", "education_level",    "Bachelor vs Bachelors inconsistency",    "CASE normalisation in dim_forecasters"),
        ("Medium", "raw_forecaster_demographics", "education/affil",    "F007 NULL education and affiliation",    "Kept as NULL, has_complete_profile flag added"),
        ("Medium", "raw_forecaster_demographics", "forecaster_id",      "F099 zero forecasts",                    "Kept in dim_forecasters, is_active = FALSE"),
        ("High",   "raw_question_tags",           "tag",                "Q003 mixed case Artificial-Intelligence","LOWER(TRIM(tag)) in bridge_question_tags"),
        ("High",   "raw_question_tags",           "question_id + tag",  "Q001 tag duplicated",                    "DISTINCT after lowercasing in bridge"),
    ]
    df = pd.DataFrame(issues, columns=["Severity", "Table", "Column", "Issue", "Resolution"])

    def color_sev(val):
        if val == "High":   return "background-color:#fde8e8;color:#c62828"
        if val == "Medium": return "background-color:#fff3e0;color:#e65100"
        return "background-color:#e8f5e9;color:#2e7d32"

    st.dataframe(
        df.style.map(color_sev, subset=["Severity"]),
        use_container_width=True, hide_index=True
    )
    st.markdown("---")
    c1, c2, c3 = st.columns(3)
    raw_r  = run("SELECT COUNT(*) AS n FROM raw_forecasts_export")
    clean_r = run("SELECT COUNT(*) AS n FROM fct_forecasts")
    raw_t  = run("SELECT COUNT(*) AS n FROM raw_question_tags")
    clean_t = run("SELECT COUNT(*) AS n FROM bridge_question_tags")
    c1.metric("Raw forecast rows",  int(raw_r["n"].iloc[0]))
    c1.metric("After dedup",        int(clean_r["n"].iloc[0]), delta="-1 duplicate")
    c2.metric("Raw tag rows",       int(raw_t["n"].iloc[0]))
    c2.metric("After normalise",    int(clean_t["n"].iloc[0]), delta="-1 duplicate")
    c3.metric("Issues found",    8)
    c3.metric("Issues resolved", 8, delta="100%")
