import duckdb

con = duckdb.connect("fri_worktest.duckdb")

tables = {
    "raw_forecasts_export": "data/forecasts_export.csv",
    "raw_forecaster_demographics": "data/forecaster_demographics.csv",
    "raw_question_tags": "data/question_tags.csv",
}

for table_name, csv_path in tables.items():
    con.execute(f"DROP TABLE IF EXISTS {table_name}")
    con.execute(
        f"CREATE TABLE {table_name} AS SELECT * FROM read_csv('{csv_path}', all_varchar=true)"
    )
    count = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
    print(f"Loaded {table_name}: {count} rows")

con.close()
print("\nSetup complete. Database: fri_worktest.duckdb")
