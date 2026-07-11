-- =============================================================================
-- Bonus Analytical Queries
-- These go beyond the required tasks. Each one ties back to something FRI
-- actually studies, not just generic data exploration.
-- =============================================================================


-- =============================================================================
-- Bonus Query 1: Belief revision analysis
--
-- For forecasters who updated their prediction on the same question,
-- show direction and magnitude of revision from first to last submission.
--
-- This matters because calibration research is not just about whether your
-- final prediction is right. It is about whether you update correctly when
-- new information arrives. Good forecasters move decisively. Poor ones anchor.
--
-- Two CTEs are needed here because DuckDB does not allow window functions
-- nested inside other window functions. We compute ROW_NUMBER first, then
-- MAX(ROW_NUMBER) in a second pass.
-- =============================================================================
WITH numbered AS (
    SELECT
        d.forecaster_id,
        d.forecaster_name,
        d.forecaster_type,
        q.question_id,
        f.prediction,
        f.forecast_timestamp,
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
    forecaster_id,
    forecaster_name,
    forecaster_type,
    question_id,
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
    END                                                             AS revision_direction,
    COUNT(*)                                                        AS total_submissions
FROM with_max
GROUP BY forecaster_id, forecaster_name, forecaster_type, question_id
HAVING COUNT(*) > 1
ORDER BY ABS(
    MAX(CASE WHEN update_number = max_update THEN prediction END) - MIN(prediction)
) DESC;


-- =============================================================================
-- Bonus Query 2: Calibration spread by forecaster type per question
--
-- Tetlock's core finding is that superforecasters not only predict better
-- but show tighter agreement with each other on well-defined questions.
-- Lower stddev among superforecasters vs public on the same question is
-- evidence of this. This query tests that hypothesis on FRI's own data.
--
-- Uses latest forecast per forecaster per question so revision history
-- does not inflate variance artificially.
-- =============================================================================
WITH latest AS (
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
    q.question_id,
    ROUND(AVG(CASE WHEN l.forecaster_type = 'superforecaster'
        THEN l.prediction END), 1)                                  AS sf_avg,
    ROUND(STDDEV(CASE WHEN l.forecaster_type = 'superforecaster'
        THEN l.prediction END), 1)                                  AS sf_stddev,
    ROUND(AVG(CASE WHEN l.forecaster_type = 'expert'
        THEN l.prediction END), 1)                                  AS expert_avg,
    ROUND(STDDEV(CASE WHEN l.forecaster_type = 'expert'
        THEN l.prediction END), 1)                                  AS expert_stddev,
    ROUND(AVG(CASE WHEN l.forecaster_type = 'public'
        THEN l.prediction END), 1)                                  AS public_avg,
    ROUND(STDDEV(CASE WHEN l.forecaster_type = 'public'
        THEN l.prediction END), 1)                                  AS public_stddev
FROM latest l
JOIN dim_questions q ON l.question_sk = q.question_sk
WHERE l.rn = 1
GROUP BY q.question_id
ORDER BY q.question_id;


-- =============================================================================
-- Bonus Query 3: Forecaster coverage and engagement
--
-- Shows which forecasters covered which questions and how active they were.
-- Sparse coverage on a question means its median is less statistically
-- meaningful and should be interpreted with more caution.
-- =============================================================================
SELECT
    d.forecaster_id,
    d.forecaster_name,
    d.forecaster_type,
    COUNT(DISTINCT f.question_sk)                                   AS questions_covered,
    COUNT(*)                                                        AS total_submissions,
    ROUND(AVG(f.prediction), 1)                                     AS avg_prediction,
    MIN(f.prediction)                                               AS min_prediction,
    MAX(f.prediction)                                               AS max_prediction
FROM fct_forecasts f
JOIN dim_forecasters d ON f.forecaster_sk = d.forecaster_sk
GROUP BY d.forecaster_id, d.forecaster_name, d.forecaster_type
ORDER BY total_submissions DESC;
