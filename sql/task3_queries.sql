-- =============================================================================
-- Task 3: Analytical Queries
-- All queries run against the dimensional model built in task2_model.sql
-- =============================================================================


-- =============================================================================
-- Query 1: For each question, how many forecasters provided a prediction
--          and what is the median predicted probability?
--
-- We use MEDIAN() which in DuckDB is an exact median, not an approximation.
-- We join to dim_questions to get the question text since fct_forecasts only
-- stores the surrogate key. The count is DISTINCT on forecaster_sk because
-- a forecaster can update their prediction multiple times on the same question
-- and we want to count them as one participant not multiple.
-- =============================================================================
SELECT
    q.question_id,
    q.question_text,
    COUNT(DISTINCT f.forecaster_sk)        AS forecaster_count,
    ROUND(MEDIAN(f.prediction), 1)         AS median_prediction,
    ROUND(AVG(f.prediction), 1)            AS mean_prediction,
    MIN(f.prediction)                      AS min_prediction,
    MAX(f.prediction)                      AS max_prediction
FROM fct_forecasts f
JOIN dim_questions q ON f.question_sk = q.question_sk
GROUP BY q.question_id, q.question_text
ORDER BY q.question_id;


-- =============================================================================
-- Query 2: How does the average predicted probability differ between
--          superforecasters and other forecaster types?
--
-- We use the most recent forecast per forecaster per question rather than
-- all updates. This gives us each forecaster's current best estimate rather
-- than averaging across their entire revision history which would
-- underweight forecasters who updated more often.
-- =============================================================================
WITH latest_forecasts AS (
    -- for each forecaster and question, take only their most recent forecast
    -- this is the fairest representation of their current belief
    SELECT
        f.forecaster_sk,
        f.question_sk,
        f.prediction,
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
    COUNT(DISTINCT forecaster_sk)          AS forecaster_count,
    COUNT(*)                               AS total_forecasts,
    ROUND(AVG(prediction), 1)             AS avg_prediction,
    ROUND(MEDIAN(prediction), 1)          AS median_prediction,
    ROUND(STDDEV(prediction), 1)          AS prediction_stddev
FROM latest_forecasts
WHERE rn = 1
GROUP BY forecaster_type
ORDER BY avg_prediction DESC;
