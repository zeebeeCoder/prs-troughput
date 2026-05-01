from datetime import datetime, timezone

import duckdb
import pandas as pd

from pr_metrics.reports import (
    _trend_icon,
    generate_contributor_report,
    generate_delivery_report,
    generate_markdown_report,
    generate_rich_terminal_report,
)
from pr_metrics.storage import write_rows_to_hive


def _ts(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def _report_connection():
    rows = pd.DataFrame([
        {
            "org": "Acme",
            "repo": "backend",
            "author": "alice",
            "created_at": _ts("2026-04-20T00:00:00"),
            "state": "merged",
            "pr_size": 120,
            "time_to_merge_hours": 12.0,
            "reviews": 2,
            "reviewers": "bob",
            "changed_files": 4,
            "time_to_first_review_hours": 2.0,
            "self_merged": False,
        },
        {
            "org": "Acme",
            "repo": "backend",
            "author": "alice",
            "created_at": _ts("2026-04-10T00:00:00"),
            "state": "merged",
            "pr_size": 80,
            "time_to_merge_hours": 18.0,
            "reviews": 1,
            "reviewers": "bob",
            "changed_files": 2,
            "time_to_first_review_hours": 3.0,
            "self_merged": False,
        },
        {
            "org": "Acme",
            "repo": "backend",
            "author": "bob",
            "created_at": _ts("2026-04-20T01:00:00"),
            "state": "open",
            "pr_size": 30,
            "time_to_merge_hours": None,
            "reviews": 0,
            "reviewers": "",
            "changed_files": 1,
            "time_to_first_review_hours": None,
            "self_merged": False,
        },
    ])
    con = duckdb.connect()
    con.register("rows", rows)
    con.execute("CREATE TABLE pr_data AS SELECT * FROM rows")
    return con


def test_trend_icon_covers_direction_cases():
    assert _trend_icon(2, None, 90, None) == ""
    assert _trend_icon(3, 2, 91, 90) == "[green]↑[/green]"
    assert _trend_icon(1, 2, 80, 90) == "[red]↓[/red]"
    assert _trend_icon(2, 2, 90, 88) == "[yellow]→[/yellow]"
    assert _trend_icon(3, 2, 80, 90) == "[yellow]↗[/yellow]"
    assert _trend_icon(1, 2, 96, 90) == "[blue]↘[/blue]"
    assert _trend_icon(5, 2, 96, 90) == "[green]↑[/green]"


def test_generate_rich_terminal_report_renders_core_sections(capsys):
    con = _report_connection()
    try:
        generate_rich_terminal_report(con, org="Acme", repo="backend")
    finally:
        con.close()

    output_text = capsys.readouterr().out
    assert "PR Metrics Dashboard - Acme / backend" in output_text
    assert "Top Contributors" in output_text
    assert "Repository Analytics" in output_text
    assert "PR Size Distribution" in output_text
    assert "Weekly Performance" in output_text
    assert "alice (2 PRs" in output_text


def test_generate_contributor_report_renders_rankings_and_health(capsys):
    con = _report_connection()
    try:
        generate_contributor_report(con, org="Acme", repo="backend")
    finally:
        con.close()

    output_text = capsys.readouterr().out
    assert "Contributor Performance Report" in output_text
    assert "Contributor Rankings" in output_text
    assert "Repository Health Indicators" in output_text
    assert "alice" in output_text


def test_generate_markdown_report_renders_core_sections(capsys):
    con = _report_connection()
    try:
        generate_markdown_report(con, org="Acme", repo="backend")
    finally:
        con.close()

    output_text = capsys.readouterr().out
    assert "# PR Metrics Report - Acme / backend" in output_text
    assert "## Author Analytics" in output_text
    assert "## Repository Analytics" in output_text
    assert "## PR Size Distribution" in output_text


def test_generate_delivery_report_renders_combined_delivery_lanes(tmp_path, capsys):
    output = tmp_path / "output"
    write_rows_to_hive(
        [
            {
                "org": "Acme",
                "repo": "backend",
                "year": 2026,
                "month": 4,
                "collected_at": _ts("2026-04-21T00:00:00"),
                "pr_number": 1,
                "author": "dev",
                "created_at": _ts("2026-04-20T00:00:00"),
                "updated_at": _ts("2026-04-20T01:00:00"),
                "state": "merged",
                "pr_size": 10,
            },
            {
                "org": "Acme",
                "repo": "backend",
                "year": 2026,
                "month": 4,
                "collected_at": _ts("2026-04-21T00:00:00"),
                "pr_number": 2,
                "author": "dev",
                "created_at": _ts("2026-04-20T00:00:00"),
                "updated_at": _ts("2026-04-20T01:00:00"),
                "state": "open",
                "pr_size": 5,
            },
        ],
        str(output / "data"),
        table_name="pr_data",
    )
    write_rows_to_hive(
        [
            {
                "org": "Acme",
                "repo": "backend",
                "year": 2026,
                "month": 4,
                "collected_at": _ts("2026-04-21T00:00:00"),
                "sha": "abc123",
                "committed_at": _ts("2026-04-20T00:00:00"),
                "subject": "fix: direct",
                "is_direct_main": True,
                "activity_class": "bug_fix",
            }
        ],
        str(output / "ledger" / "commits"),
        table_name="commits",
    )
    write_rows_to_hive(
        [
            {
                "org": "Acme",
                "repo": "backend",
                "year": 2026,
                "month": 4,
                "collected_at": _ts("2026-04-21T00:00:00"),
                "branch": "feature/no-pr",
                "head_sha": "def456",
                "last_commit_at": _ts("2026-04-20T00:00:00"),
                "last_author": "Dev",
                "ahead_main": 2,
                "behind_main": 0,
                "has_open_pr": False,
            }
        ],
        str(output / "ledger" / "branches"),
        table_name="branches",
    )

    generate_delivery_report(
        org="Acme",
        repo="backend",
        days_back=60,
        output_dir=str(output),
        branch_active_days=30,
    )

    output_text = capsys.readouterr().out
    assert "Git Delivery Ledger / backend" in output_text
    assert "Merged PRs" in output_text
    assert "Direct main commits" in output_text
    assert "Active Invisible WIP" in output_text
    assert "feature/no-pr" in output_text
    assert "bug_fix" in output_text
