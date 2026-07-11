# Task 1: Data Quality Assessment

## Summary

| # | Table | Column(s) | Issue Type | Severity |
|---|-------|-----------|------------|----------|
| 1 | raw_forecasts_export | all columns | Exact duplicate row | High |
| 2 | raw_forecasts_export | rationale | Empty string instead of NULL | Low |
| 3 | raw_forecaster_demographics | joined_date | Inconsistent date format | High |
| 4 | raw_forecaster_demographics | education_level | No controlled vocabulary | Medium |
| 5 | raw_forecaster_demographics | education_level, affiliation | Missing values (F007) | Medium |
| 6 | raw_forecaster_demographics | forecaster_id | Orphan record (F099) | Medium |
| 7 | raw_question_tags | tag | Case inconsistency (Q003) | High |
| 8 | raw_question_tags | question_id + tag | Duplicate tag assignment (Q001) | High |

---

## Issue Details

### Issue 1: Exact duplicate row in raw_forecasts_export
**Affected:** `raw_forecasts_export` — all columns  
**What it is:** F005 (Maple Syrupsworth) has two identical rows for Q002 at timestamp `2025-01-15 13:30:00`, same prediction (65), same rationale. This is not a forecast update, it is a copy paste duplication, likely from the survey platform exporting the same submission twice.  
**Why it matters:** Including both rows inflates the forecast count for Q002 and skews the median calculation.  
**Resolution:** Deduplicate using ROW_NUMBER() partitioned by forecaster_id, question_id, and forecast_timestamp during transformation. Keep the first occurrence, drop the rest.

---

### Issue 2: Empty string rationales instead of NULL
**Affected:** `raw_forecasts_export.rationale` — 3 rows (F003 on Q007, F004 on Q005, F004 on Q008)  
**What it is:** Three rows have rationale as an empty string `''` rather than a proper NULL. The survey platform allowed submission without rationale but stored it as empty text instead of nothing.  
**Why it matters:** Any IS NULL check will miss these. A COUNT(rationale) will include them as if they contain data.  
**Resolution:** NULLIF(rationale, '') during transformation to convert empty strings to proper NULLs.

---

### Issue 3: Inconsistent date format in joined_date
**Affected:** `raw_forecaster_demographics.joined_date` — F006  
**What it is:** Every other row uses ISO 8601 format (YYYY-MM-DD). F006 has "March 15, 2023" in plain English prose. Both represent the same date but DuckDB cannot cast them to DATE in a single operation without handling this case explicitly.  
**Why it matters:** A naive CAST(joined_date AS DATE) will throw an error or silently produce NULL for F006.  
**Resolution:** Use TRY_CAST first, then STRPTIME for the non-ISO row as a fallback. In the dimensional model we parse this correctly rather than dropping the row.

---

### Issue 4: No controlled vocabulary for education_level
**Affected:** `raw_forecaster_demographics.education_level`  
**What it is:** The same degree level appears under different spellings. Bachelor and Bachelors are the same thing. The source survey had a free text field instead of a dropdown.  
**Why it matters:** Any GROUP BY on education_level will split Bachelor and Bachelors into separate buckets, making counts wrong and comparisons impossible.  
**Resolution:** Normalise to a controlled set during transformation: Bachelor -> Bachelors, everything else kept as is. Document the mapping explicitly.

---

### Issue 5: Missing values for F007
**Affected:** `raw_forecaster_demographics.education_level` and `raw_forecaster_demographics.affiliation`  
**What it is:** F007 (Japan) has genuine NULLs for both education_level and affiliation. This forecaster registered but did not complete their demographic profile.  
**Why it matters:** Any analysis segmented by education level will silently exclude F007 unless NULLs are handled explicitly.  
**Resolution:** Keep the row with NULLs intact. Do not impute or drop. Flag in dim_forecasters with a boolean has_complete_profile column so downstream queries can filter deliberately rather than accidentally.

---

### Issue 6: Orphan record in demographics (F099)
**Affected:** `raw_forecaster_demographics.forecaster_id` — F099  
**What it is:** F099 appears in demographics with a full profile (Bachelors, Canada, Unicorn College) but has zero rows in raw_forecasts_export. This forecaster registered and completed their profile but never submitted a forecast.  
**Why it matters:** F099 will appear in dim_forecasters but never in fct_forecasts. Any JOIN from facts to dims will correctly exclude them. However an analysis counting registered vs active forecasters would need to account for this.  
**Resolution:** Keep F099 in dim_forecasters. Add an is_active boolean derived from whether a forecaster has at least one forecast row.

---

### Issue 7: Case inconsistency in question tags
**Affected:** `raw_question_tags.tag` — Q003  
**What it is:** Q003 is tagged with `Artificial-Intelligence` (capital A) while the same concept appears as `artificial-intelligence` (all lowercase) on every other question. These are treated as two distinct strings by any GROUP BY or JOIN on the tag column.  
**Why it matters:** A query counting questions tagged with artificial-intelligence would miss Q003 entirely. A tag frequency analysis would show two separate entries for what is conceptually one tag.  
**Resolution:** LOWER(tag) during transformation. Normalise all tags to lowercase before loading into the bridge table.

---

### Issue 8: Duplicate tag assignment for Q001
**Affected:** `raw_question_tags` — Q001 and tag `artificial-intelligence`  
**What it is:** Q001 has the artificial-intelligence tag assigned twice in the source data.  
**Why it matters:** A question with a duplicated tag will appear twice in any JOIN that expands tags, inflating counts.  
**Resolution:** Deduplicate on (question_id, tag) after normalising case, so the case fix and the dedup happen in the right order.

---

## Data Profiling Numbers

| Table | Total Rows | Issues Found |
|-------|-----------|--------------|
| raw_forecasts_export | 90 (89 after dedup) | 2 |
| raw_forecaster_demographics | 11 | 4 |
| raw_question_tags | 20 (18 after dedup and case fix) | 2 |

