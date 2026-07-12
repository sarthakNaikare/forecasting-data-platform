-- =============================================================================
-- Task 2: Dimensional Model
-- FRI Forecasting Data Platform
--
-- Design decisions:
--   1. Surrogate integer keys on all dims instead of source string IDs.
--      The source uses strings like F001 which look stable but could change
--      if the survey platform is ever migrated. Surrogate keys decouple our
--      warehouse from upstream ID schemes.
--
--   2. question_text is stored in fct_forecasts as a snapshot column.
--      Survey platforms sometimes edit question wording after forecasts are
--      submitted. Snapshotting the text at fact load time means we always
--      know what wording a forecaster actually saw, not what the question
--      says today.
--
--   3. bridge_question_tags is a separate table because question to tag is
--      a genuine many-to-many relationship. Flattening tags into dim_questions
--      would either duplicate question rows or force arrays, both of which
--      make analytical queries harder to write correctly.
--
--   4. dim_date is derived from forecast timestamps so time based queries
--      can group by year or month without parsing strings in every query.
--
--   5. All transformations happen here, not in the raw tables. The raw tables
--      stay untouched so we can always rerun this script from scratch.
-- =============================================================================


-- drop existing tables so this script is safe to rerun from scratch
DROP TABLE IF EXISTS fct_forecasts;
DROP TABLE IF EXISTS bridge_question_tags;
DROP TABLE IF EXISTS dim_date;
DROP TABLE IF EXISTS dim_questions;
DROP TABLE IF EXISTS dim_forecasters;


-- =============================================================================
-- dim_forecasters
-- One row per forecaster. Demographics merged in here rather than kept
-- in a separate table because forecaster identity and demographics are
-- always queried together and the dataset is small enough that denormalising
-- them here is the right call.
-- =============================================================================
CREATE TABLE dim_forecasters AS
WITH base AS (
    -- deduplicate the source on forecaster_id just in case, the data looks
    -- clean here but being explicit costs nothing and prevents silent issues
    -- if the source ever sends duplicates
    SELECT DISTINCT
        d.forecaster_id, -- pull from demographics not forecasts so F099 retains its ID despite having zero forecast rows
        MAX(f.forecaster_name) OVER (PARTITION BY d.forecaster_id) AS forecaster_name,
        MAX(f.forecaster_type) OVER (PARTITION BY d.forecaster_id) AS forecaster_type,

        -- normalise education_level to a controlled vocabulary
        -- Bachelor and Bachelors mean the same thing, the source had a
        -- free text field instead of a dropdown
        CASE
            WHEN TRIM(d.education_level) = 'Bachelor' THEN 'Bachelors'
            ELSE TRIM(d.education_level)
        END AS education_level,

        d.years_forecasting_experience,
        d.country,
        d.affiliation,

        -- joined_date has two formats in the source: ISO 8601 (YYYY-MM-DD)
        -- for everyone except F006 who has "March 15, 2023" in plain English.
        -- TRY_CAST handles the ISO rows. STRPTIME handles the English format.
        -- COALESCE picks whichever one worked.
        COALESCE(
            TRY_CAST(d.joined_date AS DATE),
            TRY_STRPTIME(d.joined_date, '%B %d, %Y')
        ) AS joined_date,

        -- flag forecasters who never submitted a forecast (F099)
        -- useful for distinguishing registered vs active participants
        CASE
            WHEN EXISTS (
                SELECT 1 FROM raw_forecasts_export fe
                WHERE fe.forecaster_id = d.forecaster_id
            ) THEN TRUE
            ELSE FALSE
        END AS is_active,

        -- flag forecasters with incomplete demographic profiles (F007)
        -- better to surface this explicitly than let NULLs cause silent
        -- exclusions in downstream analysis
        CASE
            WHEN d.education_level IS NULL OR d.education_level = ''
            THEN FALSE
            ELSE TRUE
        END AS has_complete_profile

    FROM raw_forecaster_demographics d
    -- left join from demographics because F099 exists in demographics
    -- but has no forecasts. we want to keep F099 in this dim.
    LEFT JOIN raw_forecasts_export f ON d.forecaster_id = f.forecaster_id
),
-- after the join we get one row per forecast for each forecaster
-- we only want one row per forecaster in this dim so we collapse here
deduped AS (
    SELECT DISTINCT
        forecaster_id,
        MAX(forecaster_name) AS forecaster_name,
        MAX(forecaster_type) AS forecaster_type,
        MAX(education_level) AS education_level,
        MAX(years_forecasting_experience) AS years_forecasting_experience,
        MAX(country) AS country,
        MAX(affiliation) AS affiliation,
        MAX(joined_date) AS joined_date,
        BOOL_OR(is_active) AS is_active,
        BOOL_OR(has_complete_profile) AS has_complete_profile
    FROM base
    GROUP BY forecaster_id
)
SELECT
    ROW_NUMBER() OVER (ORDER BY forecaster_id) AS forecaster_sk,
    forecaster_id,
    forecaster_name,
    forecaster_type,
    education_level,
    CAST(years_forecasting_experience AS INTEGER) AS years_forecasting_experience,
    country,
    affiliation,
    joined_date,
    is_active,
    has_complete_profile
FROM deduped;


-- =============================================================================
-- dim_questions
-- One row per unique question. Question text is stored here as the
-- current wording. The snapshot at time of forecast is stored in fct_forecasts.
-- =============================================================================
CREATE TABLE dim_questions AS
SELECT
    ROW_NUMBER() OVER (ORDER BY question_id) AS question_sk,
    question_id,
    -- question text is consistent across all rows for the same question_id
    -- in this dataset. taking MAX just makes the SELECT unambiguous.
    MAX(question_text) AS question_text
FROM raw_forecasts_export
GROUP BY question_id
ORDER BY question_id;


-- =============================================================================
-- bridge_question_tags
-- Many-to-many relationship between questions and tags.
-- Kept separate from dim_questions because one question can have
-- multiple tags and one tag can apply to multiple questions.
-- =============================================================================
CREATE TABLE bridge_question_tags AS
SELECT DISTINCT
    q.question_sk,
    -- normalise tags to lowercase to fix the Artificial-Intelligence
    -- vs artificial-intelligence inconsistency on Q003
    LOWER(TRIM(qt.tag)) AS tag
FROM raw_question_tags qt
JOIN dim_questions q ON qt.question_id = q.question_id
-- the DISTINCT above handles two things at once:
-- 1. the duplicate Q001 artificial-intelligence tag after lowercasing
-- 2. any other accidental duplicates from the source
ORDER BY q.question_sk, tag;


-- =============================================================================
-- dim_date
-- One row per calendar date that appears in the forecast timestamps.
-- Derived entirely from fct data rather than a pre-built calendar table
-- because we only need dates that actually have forecasts against them.
-- =============================================================================
CREATE TABLE dim_date AS
SELECT DISTINCT
    CAST(forecast_timestamp AS DATE) AS date_day,
    YEAR(CAST(forecast_timestamp AS DATE)) AS year,
    MONTH(CAST(forecast_timestamp AS DATE)) AS month,
    DAY(CAST(forecast_timestamp AS DATE)) AS day,
    DAYNAME(CAST(forecast_timestamp AS DATE)) AS day_name,
    MONTHNAME(CAST(forecast_timestamp AS DATE)) AS month_name,
    QUARTER(CAST(forecast_timestamp AS DATE)) AS quarter
FROM raw_forecasts_export
ORDER BY date_day;


-- =============================================================================
-- fct_forecasts
-- One row per forecast submission after deduplication.
-- Foreign keys point to all dimension tables.
-- prediction is cast to INTEGER here because the source stores it as VARCHAR.
-- rationale empty strings are converted to NULL for consistency.
-- question_text is snapshotted here because question wording can change
-- after forecasts are submitted on live survey platforms.
-- =============================================================================
CREATE TABLE fct_forecasts AS
WITH deduped_forecasts AS (
    -- remove the exact duplicate row for F005 on Q002
    -- ROW_NUMBER partitioned by the natural key of a forecast submission
    -- means identical rows get numbered 1, 2, 3... and we keep only 1
    SELECT
        forecaster_id,
        forecaster_name,
        forecaster_type,
        question_id,
        question_text,
        forecast_timestamp,
        prediction,
        rationale,
        ROW_NUMBER() OVER (
            PARTITION BY forecaster_id, question_id, forecast_timestamp
            ORDER BY forecaster_id
        ) AS rn
    FROM raw_forecasts_export
)
SELECT
    ROW_NUMBER() OVER (ORDER BY df.forecast_timestamp, df.forecaster_id) AS forecast_sk,
    f.forecaster_sk,
    q.question_sk,
    CAST(df.forecast_timestamp AS TIMESTAMP) AS forecast_timestamp,
    CAST(df.prediction AS INTEGER) AS prediction,
    -- convert empty string rationales to proper NULLs
    -- IS NULL checks downstream will now work correctly
    NULLIF(TRIM(df.rationale), '') AS rationale,
    -- snapshot the question text at load time
    df.question_text AS question_text_snapshot,
    CAST(df.forecast_timestamp AS DATE) AS date_day
FROM deduped_forecasts df
JOIN dim_forecasters f ON df.forecaster_id = f.forecaster_id
JOIN dim_questions q ON df.question_id = q.question_id
-- drop the duplicate row we numbered above
WHERE df.rn = 1;
