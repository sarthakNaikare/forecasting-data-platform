# FRI Forecasting Data Platform

A production-grade data engineering submission for the Forecasting Research Institute.
Built on DuckDB, FastAPI, and Streamlit. Runs with two commands.

---

## Quickstart

```bash
pip install -r requirements.txt
python setup.py
```

Then start the dashboard:

```bash
streamlit run app/dashboard.py --server.port 8501
```

Open http://localhost:8501

To run the API instead:

```bash
cd app && uvicorn api:app --reload --port 8000
```

API docs at http://localhost:8000/docs

---

## What Was Built

### Task 1: Data Quality Assessment

Eight issues found across three raw tables and documented in `task1_data_quality.md`.
Issues range from an exact duplicate forecast row to a mixed-case tag inconsistency
that would silently split one concept into two buckets in any GROUP BY query.

### Task 2: Dimensional Model

Five tables built on top of the raw data in `sql/task2_model.sql`.
raw_forecasts_export          raw_forecaster_demographics    raw_question_tags
│                               │                          │
▼                               ▼                          │
fct_forecasts ──────────── dim_forecasters                       │
│                                                          │
└──────────────────── dim_questions ──────── bridge_question_tags
│
└──────────────────── dim_date
Key design decisions:

- Surrogate integer keys on all dims. Source strings like F001 look stable
  but could change if the survey platform is ever migrated.
- question_text snapshotted in fct_forecasts. Survey platforms sometimes
  edit question wording after forecasts are submitted.
- bridge_question_tags kept separate because question to tag is a genuine
  many-to-many relationship. Flattening it would either duplicate rows or
  force arrays, both of which make analytical queries harder to write.
- dim_date derived from forecast timestamps so time-based queries can group
  by year or month without parsing strings in every query.

All transformations happen in the model SQL. Raw tables stay untouched so
the entire model can be rebuilt from scratch by rerunning the script.

### Task 3: Analytical Queries

Required queries in `sql/task3_queries.sql`:

1. For each question: forecaster count and median predicted probability.
   Uses MEDIAN() which in DuckDB is an exact median, not an approximation.
   Counts DISTINCT forecasters rather than rows to avoid inflating counts
   for forecasters who submitted multiple updates.

2. Average predicted probability by forecaster type.
   Uses each forecaster's most recent forecast per question rather than
   averaging across their full revision history. This gives each person's
   current best estimate rather than penalising active updaters.

Bonus queries in `sql/task3_bonus_queries.sql`:

3. Belief revision analysis. For each forecaster who submitted multiple
   forecasts on the same question, shows direction and magnitude of revision
   from first to last. Tied directly to FRI's calibration research mission.

4. Calibration spread per question by type. Tests Tetlock's hypothesis that
   superforecasters cluster more tightly than public forecasters on the same
   question. Confirmed on this dataset: SF avg sigma 3.9 vs public 5.4.

5. Forecaster coverage and engagement. Shows which forecasters covered which
   questions and how active they were. Sparse coverage flags questions whose
   medians should be interpreted with more caution.

---

## Beyond the Tasks

### REST API (FastAPI)

Five endpoints serving all analytical queries as live JSON:

| Endpoint | Description |
|---|---|
| GET /api/questions/summary | Task 3 Query 1 as JSON |
| GET /api/forecasters/comparison | Task 3 Query 2 as JSON |
| GET /api/forecasts/revisions | Bonus Query 1 as JSON |
| GET /api/forecasts/calibration | Bonus Query 2 as JSON |
| GET /api/forecasters/engagement | Bonus Query 3 as JSON |

Self-documenting OpenAPI interface at /docs. Single shared DuckDB connection
opened at startup via FastAPI lifespan, reused across all requests.

### Analytics Dashboard (Streamlit)

Six views built on FRI's own brand colors pulled from forecastingresearch.org:

1. Question Overview: horizontal bars with color intensity tied to probability
   level, error bars showing min/max spread.
2. Forecaster Types: average prediction with standard deviation error bars,
   plus avg/median/stddev grouped comparison.
3. Belief Revisions: scatter of first vs last prediction with a no-change
   reference line, plus net revision magnitude bars.
4. Calibration Spread: grouped bars of sigma per question per forecaster type,
   testing Tetlock's hypothesis directly on FRI's own data.
5. Engagement: submission volume per forecaster with a bubble chart mapping
   experience to average prediction.
6. Data Quality: live metrics proving every fix landed correctly, plus the
   full issue register with severity and resolution.

All queries cached at 300 second TTL via st.cache_data. Cold start cost
is roughly 400ms total across all five queries, subsequent navigation hits
cache in under 1ms.

---

## Performance

Full benchmark results in `OPTIMIZATION.md`. Summary:

| Query | Avg | Min |
|---|---|---|
| questions_summary | 40ms | 5ms |
| forecaster_comparison | 5ms | 4ms |
| belief_revisions | 8ms | 8ms |
| calibration | 5ms | 4ms |
| engagement | 5ms | 5ms |

The 40ms average on questions_summary is DuckDB's LLVM JIT compiler warming
up on first execution. All subsequent runs complete in 5ms. No indexes were
added because DuckDB's columnar engine with automatic predicate pushdown
outperforms index lookups on datasets this size.

---

## Project Structure
fri-submission/
data/
forecasts_export.csv
forecaster_demographics.csv
question_tags.csv
sql/
task2_model.sql          dimensional model
task3_queries.sql        required analytical queries
task3_bonus_queries.sql  three bonus queries
app/
api.py                   FastAPI backend
dashboard.py             Streamlit dashboard
setup.py                   loads raw CSVs into DuckDB
task1_data_quality.md      data quality assessment
OPTIMIZATION.md            benchmark results and decisions
requirements.txt           pinned dependencies
README.md                  this file
---

## What I Would Do Next

- Add dbt for transformation lineage so every table has a documented
  lineage from raw source to clean output
- Add incremental loading logic so new survey exports append rather than
  requiring a full rebuild
- Add pytest coverage for the SQL transformations, asserting row counts,
  null rates, and join cardinality after each model build
- Move the dashboard to Streamlit Cloud so FRI can access it without
  running a local server
- Add a materialized view for the calibration spread query since it is
  the most computation-heavy relative to its output size
