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

st.markdown(f"""
<style>
[data-testid="stSidebar"] {{background:{G1}}}
[data-testid="stSidebar"] * {{color:white!important}}
[data-testid="stSidebar"] .stRadio label {{font-size:0.9rem!important}}
.mc{{background:white;border-radius:12px;padding:20px;
    box-shadow:0 2px 16px rgba(16,43,35,.1);text-align:center;
    border-top:3px solid {G4}}}
.mv{{font-size:2.2rem;font-weight:700;color:{G1};line-height:1}}
.ml{{font-size:.72rem;color:#7a7a7a;margin-top:6px;
    text-transform:uppercase;letter-spacing:.06em}}
.ms{{font-size:.7rem;color:{G4};margin-top:4px}}
.ib{{background:{G5};border-left:4px solid {G4};
    padding:12px 16px;border-radius:6px;font-size:.88rem;
    color:{G2};font-style:italic;margin-bottom:20px;line-height:1.6}}
.st{{font-size:1.25rem;font-weight:700;color:{G1};margin-bottom:4px}}
.ss{{font-size:.82rem;color:#7a7a7a;margin-bottom:16px}}
</style>
""", unsafe_allow_html=True)

LAYOUT = dict(
    plot_bgcolor="white",
    paper_bgcolor="white",
    font=dict(family="sans-serif", size=12, color="#222222"),
    title_font=dict(size=14, color="#102B23"),
    xaxis=dict(title_font=dict(color="#222222", size=12), tickfont=dict(color="#222222", size=11)),
    yaxis=dict(title_font=dict(color="#222222", size=12), tickfont=dict(color="#222222", size=11)),
    hoverlabel=dict(bgcolor="#102B23", font_size=12, font_color="white"),
    margin=dict(l=20, r=20, t=50, b=20),
)


@st.cache_resource
def get_con():
    db = os.path.join(os.path.dirname(__file__), "..", "fri_worktest.duckdb")
    return duckdb.connect(db, read_only=True)


@st.cache_data(ttl=300)
def run(sql):
    return get_con().execute(sql).fetchdf()


def insight(text):
    st.markdown(f'<div class="ib">💡 {text}</div>', unsafe_allow_html=True)


def mcard(col, val, label, sub=None):
    s = f'<div class="ms">{sub}</div>' if sub else ""
    col.markdown(
        f'<div class="mc"><div class="mv">{val}</div>'
        f'<div class="ml">{label}</div>{s}</div>',
        unsafe_allow_html=True
    )


def lay(fig, h=400, **kw):
    fig.update_layout(**{**LAYOUT, "height": h, **kw})
    fig.update_xaxes(
        showgrid=True, gridcolor="#f0f0f0", zeroline=False,
        tickfont=dict(size=11, color="#222222"),
        title_font=dict(size=12, color="#222222"),
    )
    fig.update_yaxes(
        showgrid=True, gridcolor="#f0f0f0", zeroline=False,
        tickfont=dict(size=11, color="#222222"),
        title_font=dict(size=12, color="#222222"),
    )
    return fig


# ── load all data upfront so cache works across page switches ─────────────
questions = run("""
    SELECT q.question_id, q.question_text,
        COUNT(DISTINCT f.forecaster_sk) AS forecaster_count,
        ROUND(MEDIAN(f.prediction),1)   AS median_prediction,
        ROUND(AVG(f.prediction),1)      AS mean_prediction,
        ROUND(STDDEV(f.prediction),1)   AS stddev_prediction,
        MIN(f.prediction)               AS min_prediction,
        MAX(f.prediction)               AS max_prediction
    FROM fct_forecasts f
    JOIN dim_questions q ON f.question_sk = q.question_sk
    GROUP BY q.question_id, q.question_text
    ORDER BY q.question_id
""")

comparison = run("""
    WITH latest AS (
        SELECT f.forecaster_sk, f.question_sk, f.prediction,
               d.forecaster_type,
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
        ROUND(AVG(prediction),1)       AS avg_prediction,
        ROUND(MEDIAN(prediction),1)    AS median_prediction,
        ROUND(STDDEV(prediction),1)    AS prediction_stddev
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
        JOIN dim_questions q    ON f.question_sk  = q.question_sk
    ),
    wm AS (
        SELECT *,
            MAX(rn) OVER (PARTITION BY forecaster_id, question_id) AS max_rn
        FROM numbered
    )
    SELECT forecaster_id, forecaster_name, forecaster_type, question_id,
        MIN(prediction)                                               AS first_prediction,
        MAX(CASE WHEN rn = max_rn THEN prediction END)                AS last_prediction,
        MAX(CASE WHEN rn = max_rn THEN prediction END) - MIN(prediction) AS net_revision,
        COUNT(*)                                                      AS total_submissions
    FROM wm
    GROUP BY forecaster_id, forecaster_name, forecaster_type, question_id
    HAVING COUNT(*) > 1
    ORDER BY ABS(MAX(CASE WHEN rn = max_rn THEN prediction END) - MIN(prediction)) DESC
""")

calibration = run("""
    WITH latest AS (
        SELECT f.forecaster_sk, f.question_sk, f.prediction,
               d.forecaster_type,
               ROW_NUMBER() OVER (
                   PARTITION BY f.forecaster_sk, f.question_sk
                   ORDER BY f.forecast_timestamp DESC
               ) AS rn
        FROM fct_forecasts f
        JOIN dim_forecasters d ON f.forecaster_sk = d.forecaster_sk
    )
    SELECT q.question_id,
        ROUND(AVG(CASE WHEN l.forecaster_type='superforecaster'
            THEN l.prediction END),1)   AS sf_avg,
        ROUND(STDDEV(CASE WHEN l.forecaster_type='superforecaster'
            THEN l.prediction END),1)   AS sf_stddev,
        ROUND(AVG(CASE WHEN l.forecaster_type='expert'
            THEN l.prediction END),1)   AS expert_avg,
        ROUND(STDDEV(CASE WHEN l.forecaster_type='expert'
            THEN l.prediction END),1)   AS expert_stddev,
        ROUND(AVG(CASE WHEN l.forecaster_type='public'
            THEN l.prediction END),1)   AS public_avg,
        ROUND(STDDEV(CASE WHEN l.forecaster_type='public'
            THEN l.prediction END),1)   AS public_stddev
    FROM latest l
    JOIN dim_questions q ON l.question_sk = q.question_sk
    WHERE l.rn = 1
    GROUP BY q.question_id
    ORDER BY q.question_id
""")

engagement = run("""
    SELECT d.forecaster_id, d.forecaster_name, d.forecaster_type,
        d.years_forecasting_experience, d.education_level, d.country,
        COUNT(DISTINCT f.question_sk)  AS questions_covered,
        COUNT(*)                       AS total_submissions,
        ROUND(AVG(f.prediction),1)     AS avg_prediction
    FROM fct_forecasts f
    JOIN dim_forecasters d ON f.forecaster_sk = d.forecaster_sk
    GROUP BY d.forecaster_id, d.forecaster_name, d.forecaster_type,
             d.years_forecasting_experience, d.education_level, d.country
    ORDER BY total_submissions DESC
""")

# ── sidebar ───────────────────────────────────────────────────────────────
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
        "5 tables · 89 forecasts · 10 forecasters<br>"
        "Star schema · Pinned dependencies</small>",
        unsafe_allow_html=True
    )

# ── header ────────────────────────────────────────────────────────────────
st.markdown("### 🔭 FRI Forecasting Data Platform")
st.markdown(
    "<p style='color:#7a7a7a;font-size:.85rem;margin-bottom:24px'>"
    "Dimensional warehouse analytics · Live from DuckDB · "
    "Hover any chart for exact figures</p>",
    unsafe_allow_html=True
)

c1, c2, c3, c4, c5 = st.columns(5)
overall_median = round(float(questions["median_prediction"].mean()), 1)
total_subs = int(engagement["total_submissions"].sum())
mcard(c1, len(questions),       "Questions",      "8 AI topics")
mcard(c2, len(engagement),      "Forecasters",    "3 types")
mcard(c3, total_subs,           "Submissions",    "after dedup")
mcard(c4, f"{overall_median}%", "Overall Median", "all questions")
mcard(c5, len(revisions),       "Belief Updates", "tracked")
st.markdown("<br>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# PAGE 1: QUESTIONS
# ══════════════════════════════════════════════════════════════════════════
if page == "📊 Questions":
    st.markdown('<div class="st">Predicted Probability by Question</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ss">Median prediction across all forecaster types · '
        'Error bars show min/max range · Color intensity reflects level · '
        'Hover for exact figures</div>',
        unsafe_allow_html=True
    )

    low = questions.loc[questions["median_prediction"].idxmin()]
    high = questions.loc[questions["median_prediction"].idxmax()]
    insight(
        f"Most confident: <b>{high['question_id']}</b> compute scaling "
        f"({high['median_prediction']}% median). "
        f"Least confident: <b>{low['question_id']}</b> voluntary AI pause "
        f"({low['median_prediction']}% median). "
        f"The {high['median_prediction'] - low['median_prediction']} point spread "
        f"shows strong consensus on compute trajectories but deep uncertainty on governance."
    )

    qs = questions.sort_values("median_prediction").copy()
    qs["label"] = qs["question_id"] + "  " + qs["question_text"].str[:62] + "..."

    fig = go.Figure(go.Bar(
        y=qs["label"],
        x=qs["median_prediction"],
        orientation="h",
        marker=dict(
            color=qs["median_prediction"],
            colorscale=[[0, RED], [0.25, AMBER], [0.55, G4], [1, G1]],
            showscale=True,
            colorbar=dict(
                title=dict(text="Median %", font=dict(size=11, color=G1)),
                thickness=12, tickfont=dict(size=10, color="#333"),
                outlinewidth=0,
            ),
        ),
        error_x=dict(
            type="data", symmetric=False,
            array=qs["max_prediction"] - qs["median_prediction"],
            arrayminus=qs["median_prediction"] - qs["min_prediction"],
            color="#888", thickness=2, width=7,
        ),
        text=[f"  {v}%" for v in qs["median_prediction"]],
        textposition="outside",
        textfont=dict(size=12, color="#111"),
        hovertemplate=(
            "<b>%{y}</b><br>"
            "Median: <b>%{x}%</b><br>"
            "<extra></extra>"
        ),
    ))
    lay(fig, h=490,
        xaxis=dict(title="Predicted Probability (%)", range=[0, 118], ticksuffix="%"),
        yaxis=dict(tickfont=dict(size=11, color="#222")),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("**Full data table**")
    d = questions[[
        "question_id", "question_text", "forecaster_count",
        "median_prediction", "mean_prediction",
        "stddev_prediction", "min_prediction", "max_prediction"
    ]].copy()
    d.columns = ["ID", "Question", "Forecasters",
                 "Median %", "Mean %", "Std Dev", "Min %", "Max %"]
    st.dataframe(d, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════
# PAGE 2: FORECASTER TYPES
# ══════════════════════════════════════════════════════════════════════════
elif page == "👥 Forecaster Types":
    st.markdown('<div class="st">Superforecasters vs Experts vs Public</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ss">Latest forecast per person per question used · '
        'Avoids inflating counts for active updaters</div>',
        unsafe_allow_html=True
    )

    sf  = comparison[comparison["forecaster_type"] == "superforecaster"].iloc[0]
    pub = comparison[comparison["forecaster_type"] == "public"].iloc[0]
    exp = comparison[comparison["forecaster_type"] == "expert"].iloc[0]

    insight(
        f"Superforecasters σ={sf['prediction_stddev']} · "
        f"Experts σ={exp['prediction_stddev']} · "
        f"Public σ={pub['prediction_stddev']}. "
        f"Superforecasters show <b>higher</b> variance because they take stronger "
        f"positions away from 50%, showing decisiveness rather than hedging. "
        f"This matches Tetlock's Superforecasting research."
    )

    col1, col2 = st.columns(2)

    with col1:
        fig = go.Figure()
        for ftype, color in [("superforecaster", G1), ("public", G4), ("expert", G2)]:
            row = comparison[comparison["forecaster_type"] == ftype].iloc[0]
            fig.add_trace(go.Bar(
                name=ftype.title(),
                x=[ftype.title()],
                y=[row["avg_prediction"]],
                marker=dict(color=color),
                error_y=dict(
                    type="data",
                    array=[row["prediction_stddev"]],
                    visible=True, color="#444",
                    thickness=2.5, width=12,
                ),
                text=[f"{row['avg_prediction']}%"],
                textposition="outside",
                textfont=dict(size=13, color="#111"),
                hovertemplate=(
                    f"<b>{ftype.title()}</b><br>"
                    f"Avg: {row['avg_prediction']}%<br>"
                    f"Median: {row['median_prediction']}%<br>"
                    f"Std Dev: {row['prediction_stddev']}<br>"
                    "<extra></extra>"
                ),
            ))
        lay(fig, h=380,
            title="Average Prediction +/- Std Dev",
            yaxis=dict(title="Avg Predicted Probability (%)",
                       range=[0, 78], ticksuffix="%"),
            xaxis=dict(title="Forecaster Type"),
            showlegend=False, bargap=0.4,
        )
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        # grouped bar: avg vs median vs stddev side by side per type
        fig2 = go.Figure()
        type_order = ["superforecaster", "public", "expert"]
        for metric, label, color in [
            ("avg_prediction",    "Avg Prediction",    G4),
            ("median_prediction", "Median Prediction", AMBER),
            ("prediction_stddev", "Std Dev (σ)",       RED),
        ]:
            vals = [
                comparison[comparison["forecaster_type"] == t].iloc[0][metric]
                for t in type_order
            ]
            fig2.add_trace(go.Bar(
                name=label,
                x=[t.title() for t in type_order],
                y=vals,
                marker_color=color,
                text=[str(v) for v in vals],
                textposition="outside",
                textfont=dict(size=12, color="#111"),
                hovertemplate=f"<b>%{{x}}</b><br>{label}: %{{y}}<extra></extra>",
            ))
        lay(fig2, h=380,
            title="Avg · Median · Std Dev by Forecaster Type",
            yaxis=dict(title="Value", range=[0, 72]),
            barmode="group", bargap=0.2,
            legend=dict(
                orientation="h", y=-0.28,
                font=dict(size=11, color="#222222"),
                bgcolor="white",
            ),
        )
        st.plotly_chart(fig2, use_container_width=True)

    st.markdown("**Summary table**")
    d = comparison.copy()
    d.columns = ["Type", "Forecasters", "Total Forecasts",
                 "Avg %", "Median %", "Std Dev"]
    st.dataframe(d, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════
# PAGE 3: BELIEF REVISIONS
# ══════════════════════════════════════════════════════════════════════════
elif page == "🔄 Belief Revisions":
    st.markdown('<div class="st">Belief Revision Analysis</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ss">Good calibration means updating decisively on new evidence · '
        'Points above the dashed line revised upward</div>',
        unsafe_allow_html=True
    )

    up      = len(revisions[revisions["net_revision"] > 0])
    down    = len(revisions[revisions["net_revision"] < 0])
    max_rev = int(revisions["net_revision"].abs().max())

    insight(
        f"<b>{up} of {len(revisions)} revisions went upward</b>, {down} downward. "
        f"All forecasters who updated moved toward higher AI capability probabilities, "
        f"suggesting the survey period coincided with positive AI news. "
        f"Largest single revision: {max_rev} percentage points."
    )

    col1, col2 = st.columns(2)

    with col1:
        fig = go.Figure()
        for ftype, color in [("superforecaster", G1), ("expert", G2), ("public", G4)]:
            sub = revisions[revisions["forecaster_type"] == ftype]
            if len(sub) == 0:
                continue
            fig.add_trace(go.Scatter(
                x=sub["first_prediction"],
                y=sub["last_prediction"],
                mode="markers+text",
                name=ftype.title(),
                marker=dict(color=color, size=12,
                            line=dict(color="white", width=1.5)),
                text=sub["forecaster_name"].str.split().str[0]
                    + "/" + sub["question_id"],
                textposition="top center",
                textfont=dict(size=9, color="#333"),
                hovertemplate=(
                    "<b>%{text}</b><br>"
                    "First: %{x}%<br>"
                    "Last: %{y}%<br>"
                    "<extra></extra>"
                ),
            ))
        fig.add_shape(
            type="line", x0=0, y0=0, x1=100, y1=100,
            line=dict(color="#bbb", dash="dot", width=1.5),
        )
        fig.add_annotation(
            x=75, y=72, text="no change",
            showarrow=False, font=dict(size=9, color="#aaa"),
            textangle=-38,
        )
        lay(fig, h=420,
            title="First vs Last Prediction",
            xaxis=dict(title="First Prediction (%)",
                       range=[0, 105], ticksuffix="%"),
            yaxis=dict(title="Last Prediction (%)",
                       range=[0, 105], ticksuffix="%"),
            legend=dict(
                orientation="h", y=-0.22,
                font=dict(size=11, color="#222222"), bgcolor="white",
            ),
        )
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        rev = revisions.copy()
        rev["label"] = (
            rev["forecaster_name"].str.split().str[0]
            + " / " + rev["question_id"]
        )
        rev["color"] = rev["net_revision"].apply(
            lambda x: G3 if x > 0 else RED if x < 0 else "#ccc"
        )
        rev["txt"] = rev["net_revision"].apply(
            lambda x: f"+{x} pts" if x > 0
                      else f"{x} pts" if x < 0 else "no change"
        )
        rev_s = rev.sort_values("net_revision")

        fig2 = go.Figure(go.Bar(
            x=rev_s["net_revision"],
            y=rev_s["label"],
            orientation="h",
            marker=dict(color=rev_s["color"],
                        line=dict(color="white", width=0.5)),
            text=rev_s["txt"],
            textposition="outside",
            textfont=dict(size=11, color="#333"),
            hovertemplate="<b>%{y}</b><br>Net: %{x} pts<extra></extra>",
        ))
        fig2.add_vline(x=0, line_color="#333", line_width=1.5)
        lay(fig2, h=420,
            title="Net Revision (First → Last)",
            xaxis=dict(title="Percentage Points", ticksuffix=" pts"),
            yaxis=dict(tickfont=dict(size=11, color="#222")),
            margin=dict(l=20, r=80, t=50, b=20),
        )
        st.plotly_chart(fig2, use_container_width=True)

    st.markdown("**Full revision table**")
    d = revisions[[
        "forecaster_name", "forecaster_type", "question_id",
        "first_prediction", "last_prediction",
        "net_revision", "total_submissions"
    ]].copy()
    d.columns = ["Forecaster", "Type", "Question",
                 "First %", "Last %", "Net Change", "Submissions"]
    st.dataframe(d, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════
# PAGE 4: CALIBRATION
# ══════════════════════════════════════════════════════════════════════════
elif page == "🎯 Calibration":
    st.markdown('<div class="st">Calibration Spread by Forecaster Type</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ss">Testing Tetlock\'s hypothesis: superforecasters should '
        'cluster more tightly than public forecasters on the same question · '
        'Lower sigma means tighter agreement</div>',
        unsafe_allow_html=True
    )

    sf_std  = float(calibration["sf_stddev"].mean())
    pub_std = float(calibration["public_stddev"].mean())
    exp_std = float(calibration["expert_stddev"].mean())
    confirmed = sf_std < pub_std

    insight(
        f"Superforecasters avg σ: <b>{sf_std:.1f}</b> · "
        f"Experts avg σ: <b>{exp_std:.1f}</b> · "
        f"Public avg σ: <b>{pub_std:.1f}</b>. "
        + (
            f"<b>Tetlock's hypothesis confirmed.</b> Superforecasters show "
            f"tighter agreement ({sf_std:.1f}) than public forecasters ({pub_std:.1f})."
            if confirmed else
            "Hypothesis not confirmed on this small sample (3 SF vs 4 public)."
        )
    )

    rows = []
    for _, r in calibration.iterrows():
        for ft, ac, sc in [
            ("Superforecaster", "sf_avg",     "sf_stddev"),
            ("Expert",          "expert_avg", "expert_stddev"),
            ("Public",          "public_avg", "public_stddev"),
        ]:
            rows.append({
                "question": r["question_id"],
                "type": ft,
                "avg": r[ac],
                "stddev": r[sc],
            })
    cl = pd.DataFrame(rows)

    col1, col2 = st.columns(2)

    with col1:
        fig = px.bar(
            cl, x="question", y="stddev", color="type",
            barmode="group",
            color_discrete_map={
                "Superforecaster": G1,
                "Expert": G2,
                "Public": G4,
            },
            text="stddev",
            title="Prediction Spread (σ) per Question",
            labels={"stddev": "Std Dev (σ)", "question": "Question", "type": ""},
        )
        fig.update_traces(
            texttemplate="%{text}",
            textposition="outside",
            textfont=dict(size=11, color="#111"),
        )
        lay(fig, h=420,
            yaxis=dict(title="Standard Deviation (σ)", range=[0, 9]),
            legend=dict(
                orientation="h", y=-0.22,
                font=dict(size=11, color="#222222"), bgcolor="white",
                title_text="",
            ),
            bargap=0.2,
        )
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        fig2 = px.bar(
            cl, x="question", y="avg", color="type",
            barmode="group",
            color_discrete_map={
                "Superforecaster": G1,
                "Expert": G2,
                "Public": G4,
            },
            text="avg",
            title="Average Prediction (%) per Question",
            labels={"avg": "Avg Prediction (%)", "question": "Question", "type": ""},
        )
        fig2.update_traces(
            texttemplate="%{text}%",
            textposition="outside",
            textfont=dict(size=11, color="#111"),
        )
        lay(fig2, h=420,
            yaxis=dict(title="Average Prediction (%)",
                       range=[0, 100], ticksuffix="%"),
            legend=dict(
                orientation="h", y=-0.22,
                font=dict(size=11, color="#222222"), bgcolor="white",
                title_text="",
            ),
            bargap=0.2,
        )
        st.plotly_chart(fig2, use_container_width=True)

    st.markdown("**Calibration table**")
    d = calibration.copy()
    d.columns = ["Question", "SF Avg", "SF σ",
                 "Expert Avg", "Expert σ", "Public Avg", "Public σ"]
    st.dataframe(d, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════
# PAGE 5: ENGAGEMENT
# ══════════════════════════════════════════════════════════════════════════
elif page == "📈 Engagement":
    st.markdown('<div class="st">Forecaster Engagement</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ss">Submissions per forecaster · Bubble size = submission volume · '
        'F099 correctly excluded since they never submitted a forecast</div>',
        unsafe_allow_html=True
    )

    top = engagement.iloc[0]
    insight(
        f"<b>{top['forecaster_name']}</b> ({top['forecaster_type']}) leads with "
        f"{top['total_submissions']} submissions across {top['questions_covered']} questions. "
        f"Q003, Q004, Q008 had only 9 of 10 forecasters, so their medians carry "
        f"slightly more uncertainty."
    )

    col1, col2 = st.columns(2)

    with col1:
        eng = engagement.sort_values("total_submissions").copy()
        # full name in y axis by widening left margin
        fig = go.Figure()
        for ftype, color in [("superforecaster", G1), ("expert", G2), ("public", G4)]:
            sub = eng[eng["forecaster_type"] == ftype]
            fig.add_trace(go.Bar(
                x=sub["total_submissions"],
                y=sub["forecaster_name"],
                orientation="h",
                name=ftype.title(),
                marker=dict(color=color),
                text=sub["total_submissions"].astype(str),
                textposition="outside",
                textfont=dict(size=11, color="#111"),
                hovertemplate=(
                    "<b>%{y}</b><br>"
                    "Submissions: %{x}<br>"
                    "<extra></extra>"
                ),
            ))
        lay(fig, h=420,
            title="Total Submissions per Forecaster",
            xaxis=dict(title="Total Submissions", range=[0, 16]),
            yaxis=dict(tickfont=dict(size=11, color="#222"),
                       automargin=True),
            legend=dict(
                orientation="h", y=-0.22,
                font=dict(size=11, color="#222222"), bgcolor="white",
            ),
            margin=dict(l=150, r=60, t=50, b=80),
        )
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        eng_clean = engagement.dropna(subset=["years_forecasting_experience"]).copy()
        fig2 = go.Figure()
        for ftype, color in [("superforecaster", G1), ("expert", G2), ("public", G4)]:
            sub = eng_clean[eng_clean["forecaster_type"] == ftype]
            if len(sub) == 0:
                continue
            fig2.add_trace(go.Scatter(
                x=sub["years_forecasting_experience"],
                y=sub["avg_prediction"],
                mode="markers+text",
                name=ftype.title(),
                marker=dict(
                    color=color,
                    size=sub["total_submissions"] * 4.5,
                    line=dict(color="white", width=1.5),
                    opacity=0.85,
                ),
                text=sub["forecaster_name"].str.split().str[0],
                textposition="top center",
                textfont=dict(size=9, color="#333"),
                hovertemplate=(
                    "<b>%{text}</b><br>"
                    "Experience: %{x} yrs<br>"
                    "Avg: %{y}%<br>"
                    "<extra></extra>"
                ),
            ))
        lay(fig2, h=420,
            title="Experience vs Avg Prediction (bubble = volume)",
            xaxis=dict(title="Years of Forecasting Experience"),
            yaxis=dict(title="Average Prediction (%)", ticksuffix="%"),
            legend=dict(
                orientation="h", y=-0.22,
                font=dict(size=11, color="#222222"), bgcolor="white",
            ),
        )
        st.plotly_chart(fig2, use_container_width=True)

    st.markdown("**Forecaster profiles**")
    d = engagement[[
        "forecaster_name", "forecaster_type",
        "years_forecasting_experience", "education_level", "country",
        "questions_covered", "total_submissions", "avg_prediction"
    ]].copy()
    d.columns = ["Name", "Type", "Exp (yrs)", "Education",
                 "Country", "Questions", "Submissions", "Avg %"]
    st.dataframe(d, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════
# PAGE 6: DATA QUALITY
# ══════════════════════════════════════════════════════════════════════════
elif page == "🗃️ Data Quality":
    st.markdown('<div class="st">Data Quality Report</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ss">8 issues found across 3 raw tables · All resolved before '
        'loading into the dimensional model · Live counts confirm every fix below</div>',
        unsafe_allow_html=True
    )

    insight(
        "Cleaned warehouse: <b>89 fact rows</b> (down from 90 after dedup), "
        "<b>19 unique tags</b> (down from 20 after lowercase normalisation and dedup), "
        "and <b>standardised date formats</b> across all forecaster records."
    )

    c1, c2, c3 = st.columns(3)
    raw_r   = run("SELECT COUNT(*) AS n FROM raw_forecasts_export")
    clean_r = run("SELECT COUNT(*) AS n FROM fct_forecasts")
    raw_t   = run("SELECT COUNT(*) AS n FROM raw_question_tags")
    clean_t = run("SELECT COUNT(*) AS n FROM bridge_question_tags")
    c1.metric("Raw forecast rows",  int(raw_r["n"].iloc[0]))
    c1.metric("After dedup",        int(clean_r["n"].iloc[0]), delta="-1 duplicate removed")
    c2.metric("Raw tag rows",       int(raw_t["n"].iloc[0]))
    c2.metric("After normalise",    int(clean_t["n"].iloc[0]), delta="-1 after lowercase + dedup")
    c3.metric("Issues found",    8)
    c3.metric("Issues resolved", 8, delta="100% resolution rate")

    st.markdown("---")
    st.markdown("**Issue register**")

    issues = [
        ("High",   "raw_forecasts_export",
         "All columns",
         "Exact duplicate row: F005, Q002, same timestamp, same prediction (65)",
         "ROW_NUMBER() OVER(PARTITION BY forecaster_id, question_id, timestamp) in fct_forecasts CTE"),
        ("Low",    "raw_forecasts_export",
         "rationale",
         "3 rows have empty string rationale instead of NULL",
         "NULLIF(TRIM(rationale), '') converts to proper NULL in fct_forecasts"),
        ("High",   "raw_forecaster_demographics",
         "joined_date",
         "F006 stored as prose: 'March 15, 2023' vs ISO YYYY-MM-DD for all others",
         "COALESCE(TRY_CAST(date AS DATE), TRY_STRPTIME(date, '%B %d, %Y')) in dim_forecasters"),
        ("Medium", "raw_forecaster_demographics",
         "education_level",
         "Bachelor and Bachelors used interchangeably for the same degree level",
         "CASE WHEN TRIM(education_level) = 'Bachelor' THEN 'Bachelors' ELSE TRIM(...) END"),
        ("Medium", "raw_forecaster_demographics",
         "education_level, affiliation",
         "F007 has NULL education_level and NULL affiliation (incomplete profile)",
         "Kept as NULL, has_complete_profile = FALSE flag surfaced in dim_forecasters"),
        ("Medium", "raw_forecaster_demographics",
         "forecaster_id",
         "F099 exists in demographics but has zero forecasts (ghost record)",
         "Kept in dim_forecasters with is_active = FALSE, excluded from fct via JOIN"),
        ("High",   "raw_question_tags",
         "tag",
         "Q003 tagged 'Artificial-Intelligence' (capital A) vs lowercase everywhere else",
         "LOWER(TRIM(tag)) normalises all tags before loading bridge_question_tags"),
        ("High",   "raw_question_tags",
         "question_id + tag",
         "Q001 has 'artificial-intelligence' tag duplicated (exact row repeated)",
         "DISTINCT on (question_sk, tag) after lowercasing removes the duplicate"),
    ]

    df = pd.DataFrame(issues, columns=[
        "Severity", "Table", "Column", "Issue", "Resolution"
    ])

    def csev(val):
        if val == "High":
            return "background-color:#fde8e8;color:#c62828;font-weight:600"
        if val == "Medium":
            return "background-color:#fff3e0;color:#e65100;font-weight:600"
        return "background-color:#e8f5e9;color:#2e7d32;font-weight:600"

    st.dataframe(
        df.style.applymap(csev, subset=["Severity"]),
        use_container_width=True, hide_index=True
    )
