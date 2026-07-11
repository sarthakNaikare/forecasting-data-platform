"""
FRI Forecasting Data Platform - REST API

Serves analytical query results from the DuckDB dimensional warehouse.
Five endpoints, each mapping to a specific research question about
forecaster behavior and prediction patterns.

Design decisions:
- Single shared DuckDB connection opened at startup and reused across
  requests. DuckDB is embedded and single process so this is safe and
  faster than reconnecting per request.
- All SQL lives inline here rather than in separate files so the API
  is self contained and easy to run without worrying about relative paths.
- CORS is open for all origins so the dashboard can call this API
  regardless of what port it is served from.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import duckdb
import os


DB_PATH = os.path.join(os.path.dirname(__file__), "..", "fri_worktest.duckdb")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Open the database connection once when the server starts and close it
    cleanly when the server shuts down. This is the FastAPI recommended
    pattern for shared resources that should persist across requests.
    """
    app.state.db = duckdb.connect(DB_PATH, read_only=True)
    print(f"Connected to database: {DB_PATH}")
    yield
    app.state.db.close()
    print("Database connection closed")


app = FastAPI(
    title="FRI Forecasting Data Platform",
    description="Analytical API over the FRI forecasting dimensional warehouse",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def query(app, sql: str) -> list[dict]:
    """
    Run a SQL query against the shared connection and return results as
    a list of dicts so FastAPI can serialise them directly to JSON.
    Using fetchdf() then to_dict() gives us proper Python types rather
    than raw DuckDB types which can cause JSON serialisation issues.
    """
    try:
        result = app.state.db.execute(sql).fetchdf()
        return result.to_dict(orient="records")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
def root():
    return {
        "name": "FRI Forecasting Data Platform",
        "version": "1.0.0",
        "endpoints": [
            "/api/questions/summary",
            "/api/forecasters/comparison",
            "/api/forecasts/revisions",
            "/api/forecasts/calibration",
            "/api/forecasters/engagement",
        ],
        "docs": "/docs",
    }


@app.get("/api/questions/summary")
async def get_questions_summary():
    """
    For each question: forecaster count, median prediction, mean, min, max.
    Task 3 Query 1 served as a live API endpoint.
    """
    sql = """
        SELECT
            q.question_id,
            q.question_text,
            COUNT(DISTINCT f.forecaster_sk)     AS forecaster_count,
            ROUND(MEDIAN(f.prediction), 1)      AS median_prediction,
            ROUND(AVG(f.prediction), 1)         AS mean_prediction,
            MIN(f.prediction)                   AS min_prediction,
            MAX(f.prediction)                   AS max_prediction
        FROM fct_forecasts f
        JOIN dim_questions q ON f.question_sk = q.question_sk
        GROUP BY q.question_id, q.question_text
        ORDER BY q.question_id
    """
    return query(app, sql)


@app.get("/api/forecasters/comparison")
async def get_forecaster_comparison():
    """
    Average and median prediction by forecaster type.
    Task 3 Query 2 served as a live API endpoint.
    Uses latest forecast per forecaster per question to avoid
    inflating counts for active updaters.
    """
    sql = """
        WITH latest AS (
            SELECT
                f.forecaster_sk, f.question_sk, f.prediction,
                d.forecaster_type,
                ROW_NUMBER() OVER (
                    PARTITION BY f.forecaster_sk, f.question_sk
                    ORDER BY f.forecast_timestamp DESC
                ) AS rn
            FROM fct_forecasts f
            JOIN dim_forecasters d ON f.forecaster_sk = d.forecaster_sk
        )
        SELECT
            forecaster_type,
            COUNT(DISTINCT forecaster_sk)       AS forecaster_count,
            COUNT(*)                            AS total_forecasts,
            ROUND(AVG(prediction), 1)           AS avg_prediction,
            ROUND(MEDIAN(prediction), 1)        AS median_prediction,
            ROUND(STDDEV(prediction), 1)        AS prediction_stddev
        FROM latest
        WHERE rn = 1
        GROUP BY forecaster_type
        ORDER BY avg_prediction DESC
    """
    return query(app, sql)


@app.get("/api/forecasts/revisions")
async def get_forecast_revisions():
    """
    Belief revision analysis: for forecasters who updated their prediction,
    show direction and magnitude of change from first to last submission.
    Bonus Query 1.
    """
    sql = """
        WITH numbered AS (
            SELECT
                d.forecaster_id, d.forecaster_name, d.forecaster_type,
                q.question_id,
                f.prediction, f.forecast_timestamp,
                ROW_NUMBER() OVER (
                    PARTITION BY f.forecaster_sk, f.question_sk
                    ORDER BY f.forecast_timestamp
                ) AS update_number
            FROM fct_forecasts f
            JOIN dim_forecasters d ON f.forecaster_sk = d.forecaster_sk
            JOIN dim_questions q ON f.question_sk = q.question_sk
        ),
        with_max AS (
            SELECT *,
                MAX(update_number) OVER (
                    PARTITION BY forecaster_id, question_id
                ) AS max_update
            FROM numbered
        )
        SELECT
            forecaster_id, forecaster_name, forecaster_type, question_id,
            MIN(prediction)                                                 AS first_prediction,
            MAX(CASE WHEN update_number = max_update THEN prediction END)   AS last_prediction,
            MAX(CASE WHEN update_number = max_update THEN prediction END)
                - MIN(prediction)                                           AS net_revision,
            CASE
                WHEN MAX(CASE WHEN update_number = max_update THEN prediction END)
                    > MIN(prediction) THEN 'revised up'
                WHEN MAX(CASE WHEN update_number = max_update THEN prediction END)
                    < MIN(prediction) THEN 'revised down'
                ELSE 'no change'
            END AS revision_direction,
            COUNT(*) AS total_submissions
        FROM with_max
        GROUP BY forecaster_id, forecaster_name, forecaster_type, question_id
        HAVING COUNT(*) > 1
        ORDER BY ABS(
            MAX(CASE WHEN update_number = max_update THEN prediction END)
            - MIN(prediction)
        ) DESC
    """
    return query(app, sql)


@app.get("/api/forecasts/calibration")
async def get_calibration_spread():
    """
    Calibration spread by forecaster type per question.
    Tests Tetlock's hypothesis that superforecasters show tighter
    agreement with each other than public forecasters on the same question.
    Bonus Query 2.
    """
    sql = """
        WITH latest AS (
            SELECT
                f.forecaster_sk, f.question_sk, f.prediction,
                d.forecaster_type,
                ROW_NUMBER() OVER (
                    PARTITION BY f.forecaster_sk, f.question_sk
                    ORDER BY f.forecast_timestamp DESC
                ) AS rn
            FROM fct_forecasts f
            JOIN dim_forecasters d ON f.forecaster_sk = d.forecaster_sk
        )
        SELECT
            q.question_id,
            ROUND(AVG(CASE WHEN l.forecaster_type = 'superforecaster'
                THEN l.prediction END), 1)      AS sf_avg,
            ROUND(STDDEV(CASE WHEN l.forecaster_type = 'superforecaster'
                THEN l.prediction END), 1)      AS sf_stddev,
            ROUND(AVG(CASE WHEN l.forecaster_type = 'expert'
                THEN l.prediction END), 1)      AS expert_avg,
            ROUND(STDDEV(CASE WHEN l.forecaster_type = 'expert'
                THEN l.prediction END), 1)      AS expert_stddev,
            ROUND(AVG(CASE WHEN l.forecaster_type = 'public'
                THEN l.prediction END), 1)      AS public_avg,
            ROUND(STDDEV(CASE WHEN l.forecaster_type = 'public'
                THEN l.prediction END), 1)      AS public_stddev
        FROM latest l
        JOIN dim_questions q ON l.question_sk = q.question_sk
        WHERE l.rn = 1
        GROUP BY q.question_id
        ORDER BY q.question_id
    """
    return query(app, sql)


@app.get("/api/forecasters/engagement")
async def get_forecaster_engagement():
    """
    Per forecaster: questions covered, total submissions, prediction range.
    Bonus Query 3. Useful for identifying the most active participants
    and questions with sparse coverage.
    """
    sql = """
        SELECT
            d.forecaster_id, d.forecaster_name, d.forecaster_type,
            COUNT(DISTINCT f.question_sk)       AS questions_covered,
            COUNT(*)                            AS total_submissions,
            ROUND(AVG(f.prediction), 1)         AS avg_prediction,
            MIN(f.prediction)                   AS min_prediction,
            MAX(f.prediction)                   AS max_prediction
        FROM fct_forecasts f
        JOIN dim_forecasters d ON f.forecaster_sk = d.forecaster_sk
        GROUP BY d.forecaster_id, d.forecaster_name, d.forecaster_type
        ORDER BY total_submissions DESC
    """
    return query(app, sql)
