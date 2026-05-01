import duckdb

from pr_metrics.storage import write_rows_to_hive


def test_write_rows_to_hive_preserves_nullable_string_schema(tmp_path):
    rows = [
        {
            "org": "Acme",
            "repo": "backend",
            "year": 2026,
            "month": 4,
            "pr_number": 1,
            "author": "dev",
            "state": "open",
            "ci_state": None,
            "task_id": None,
            "spec_name": None,
        }
    ]

    output_dir = tmp_path / "data"
    write_rows_to_hive(rows, str(output_dir), table_name="pr_data")

    con = duckdb.connect()
    try:
        schema = con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{output_dir}/**/*.parquet', hive_partitioning=true)"
        ).fetchdf()
    finally:
        con.close()

    types = dict(zip(schema["column_name"], schema["column_type"]))
    assert types["ci_state"] == "VARCHAR"
    assert types["task_id"] == "VARCHAR"
    assert types["spec_name"] == "VARCHAR"
