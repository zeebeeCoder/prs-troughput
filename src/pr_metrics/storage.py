#!/usr/bin/env python3
"""DuckDB-based storage with Hive partitioning for PR metrics data."""

import duckdb
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd


STRING_COLUMNS_BY_TABLE = {
    "pr_data": (
        "org", "repo", "author", "title", "url", "state", "head_ref", "base_ref",
        "head_sha", "reviewers", "review_decision", "requested_reviewers", "ci_state",
        "mergeable", "merge_state_status", "merged_by", "labels", "task_id", "spec_name",
    ),
    "commits": (
        "org", "repo", "sha", "author_name", "author_email", "committer_name",
        "committer_email", "subject", "body", "branch_refs", "top_level_dirs", "file_exts",
        "task_id", "spec_name", "conventional_type", "conventional_scope", "activity_class",
    ),
    "branches": (
        "org", "repo", "branch", "head_sha", "default_branch", "default_head_sha",
        "last_author", "pr_title", "pr_url", "task_id", "spec_name",
    ),
    "commit_files": (
        "org", "repo", "sha", "path", "status", "top_level_dir", "extension",
    ),
}


def coerce_table_schema(df, table_name):
    """Coerce known nullable text fields so all-null columns stay VARCHAR in Parquet."""
    for column in STRING_COLUMNS_BY_TABLE.get(table_name, ()):  # keep generic writer usable for unknown tables
        if column not in df.columns:
            df[column] = pd.Series(pd.NA, index=df.index, dtype="string")
        else:
            df[column] = df[column].astype("string")
    return df


def get_partition_path(org, repo, created_at, base_dir="output/data"):
    """Generate Hive-style partition path for a PR

    Args:
        org: Organization name
        repo: Repository name
        created_at: datetime object for the PR creation time
        base_dir: Base directory for data storage

    Returns:
        Path object for the partition directory
    """
    year = created_at.year
    month = created_at.month

    partition_dir = Path(base_dir) / f"org={org}" / f"repo={repo}" / f"year={year}" / f"month={month:02d}"
    return partition_dir


def write_rows_to_hive(rows, base_dir, table_name="dataset", partition_by=("org", "repo", "year", "month")):
    """Write generic row dictionaries to Hive-partitioned parquet files using DuckDB."""
    if not rows:
        print(f"⚠️  No {table_name} data to write")
        return

    Path(base_dir).mkdir(parents=True, exist_ok=True)
    df = coerce_table_schema(pd.DataFrame(rows), table_name)
    con = duckdb.connect()

    try:
        con.register("_rows_df", df)
        con.execute(f"CREATE TEMP TABLE {table_name} AS SELECT * FROM _rows_df")
        partition_cols = ', '.join(partition_by)
        con.execute(f"""
            COPY {table_name} TO '{base_dir}'
            (FORMAT PARQUET, PARTITION_BY ({partition_cols}), OVERWRITE_OR_IGNORE)
        """)

        partitions = {
            tuple(row.get(col) for col in partition_by)
            for row in rows
        }
        print(f"✓ Wrote {len(rows)} {table_name} rows to {len(partitions)} partition(s) in {base_dir}")
    finally:
        con.close()


def write_to_hive(pr_data_list, org, base_dir="output/data"):
    """Write PR data to Hive-partitioned parquet files using DuckDB

    Args:
        pr_data_list: List of PR dictionaries with all fields
        org: Organization name
        base_dir: Base directory for Hive partitions
    """
    write_rows_to_hive(pr_data_list, base_dir=base_dir, table_name="pr_data")


def load_from_hive(org=None, repo=None, base_dir="output/data", days_back=None):
    """Load PR data from Hive partitions using DuckDB

    Args:
        org: Filter by organization (None for all orgs)
        repo: Filter by repository (None for all repos)
        base_dir: Base directory for Hive partitions
        days_back: Filter to only PRs from last N days

    Returns:
        tuple: (DuckDB connection, view_name) or (None, None) if no data
    """
    # Create DuckDB connection (in-memory)
    con = duckdb.connect()

    # Build the query
    data_path = f"{base_dir}/**/*.parquet"

    # Base query with Hive partitioning enabled
    # union_by_name=true allows reading files with different schemas (handles schema evolution)
    query = f"""
        CREATE OR REPLACE VIEW pr_data AS
        SELECT * FROM read_parquet('{data_path}', hive_partitioning=true, union_by_name=true)
    """

    # Add WHERE clauses for filtering
    where_clauses = []

    if org:
        where_clauses.append(f"org = '{org}'")

    if repo:
        where_clauses.append(f"repo = '{repo}'")

    if days_back:
        cutoff_date = datetime.now() - timedelta(days=days_back)
        cutoff_str = cutoff_date.strftime('%Y-%m-%d')
        where_clauses.append(f"created_at >= '{cutoff_str}'")

    if where_clauses:
        query = query.replace(
            "union_by_name=true)",
            f"union_by_name=true) WHERE {' AND '.join(where_clauses)}"
        )

    try:
        # Create the view
        con.execute(query)

        # Verify data exists
        count = con.execute("SELECT COUNT(*) FROM pr_data").fetchone()[0]
        if count == 0:
            print("ℹ️  No data found in Hive partitions matching criteria")
            con.close()
            return None, None

        print(f"✓ Loaded {count} PRs from Hive partitions into DuckDB view")
        return con, "pr_data"

    except Exception as e:
        # Handle case where no Hive data exists yet
        if "No files found" in str(e) or "does not exist" in str(e):
            print(f"ℹ️  No Hive-partitioned data found in {base_dir}")
            con.close()
            return None, None
        raise


def load_hive_dataset(dataset_dir, view_name, org=None, repo=None, days_back=None, date_column="created_at"):
    """Load a Hive-partitioned ledger dataset into DuckDB.

    Returns (connection, view_name) or (None, None) when no data exists.
    """
    con = duckdb.connect()
    data_path = f"{dataset_dir}/**/*.parquet"
    where_clauses = []

    if org:
        where_clauses.append(f"org = '{org}'")
    if repo:
        where_clauses.append(f"repo = '{repo}'")
    if days_back and date_column:
        cutoff_date = datetime.now() - timedelta(days=days_back)
        cutoff_str = cutoff_date.strftime('%Y-%m-%d')
        where_clauses.append(f"{date_column} >= '{cutoff_str}'")

    query = f"""
        CREATE OR REPLACE VIEW {view_name} AS
        SELECT * FROM read_parquet('{data_path}', hive_partitioning=true, union_by_name=true)
    """
    if where_clauses:
        query += f" WHERE {' AND '.join(where_clauses)}"

    try:
        con.execute(query)
        count = con.execute(f"SELECT COUNT(*) FROM {view_name}").fetchone()[0]
        if count == 0:
            con.close()
            return None, None
        return con, view_name
    except Exception as e:
        if "No files found" in str(e) or "does not exist" in str(e):
            con.close()
            return None, None
        raise


def load_from_legacy(org=None, output_dir="output"):
    """Load data from legacy timestamped parquet files into DuckDB

    Args:
        org: Filter by organization name (will be sanitized for file matching)
        output_dir: Directory containing legacy files

    Returns:
        tuple: (DuckDB connection, view_name) or (None, None)
    """
    from .utils import sanitize_org_name

    if org:
        # Sanitize org name for legacy file pattern matching
        sanitized_org = sanitize_org_name(org)
        pattern = f"pr_data_{sanitized_org}_*.parquet"
        files = sorted(Path(output_dir).glob(pattern), reverse=True)
    else:
        files = sorted(Path(output_dir).glob("pr_data_*.parquet"), reverse=True)

    # Try loading files from newest to oldest, skipping corrupted ones
    for filepath in files:
        try:
            # Create DuckDB connection and load the file
            con = duckdb.connect()
            con.execute(f"""
                CREATE OR REPLACE VIEW pr_data AS
                SELECT * FROM read_parquet('{filepath}')
            """)

            # Verify it loaded
            count = con.execute("SELECT COUNT(*) FROM pr_data").fetchone()[0]
            print(f"✓ Loaded {count} PRs from legacy file {filepath.name}")
            return con, "pr_data"

        except Exception as e:
            print(f"⚠️  Skipping corrupted file {filepath.name}: {str(e)[:80]}")
            continue

    return None, None


def load_data(org=None, repo=None, base_dir="output/data", legacy_dir="output", days_back=None):
    """Smart loader: tries Hive partitions first, falls back to legacy files

    Args:
        org: Organization name to filter
        repo: Repository name to filter
        base_dir: Base directory for Hive partitions
        legacy_dir: Directory for legacy timestamped files
        days_back: Filter to only PRs from last N days

    Returns:
        tuple: (DuckDB connection, view_name) or (None, None)
        Note: Caller is responsible for closing the connection when done
    """
    # Try Hive-partitioned data first
    con, view_name = load_from_hive(org, repo, base_dir, days_back)

    if con is not None:
        return con, view_name

    # Fallback to legacy files
    print("ℹ️  Falling back to legacy file format...")
    con, view_name = load_from_legacy(org, legacy_dir)

    if con is not None:
        # Apply filters if specified (create filtered view)
        filters = []
        if days_back:
            cutoff_date = datetime.now() - timedelta(days=days_back)
            cutoff_str = cutoff_date.strftime('%Y-%m-%d')
            filters.append(f"created_at >= '{cutoff_str}'")
        if repo:
            filters.append(f"repo = '{repo}'")

        if filters:
            where_clause = " AND ".join(filters)
            con.execute(f"""
                CREATE OR REPLACE VIEW pr_data_filtered AS
                SELECT * FROM {view_name}
                WHERE {where_clause}
            """)
            return con, "pr_data_filtered"
        return con, view_name

    return None, None
