from datetime import datetime, timezone

from pr_metrics.insights import render_dataframe, run_insight
from pr_metrics.storage import write_rows_to_hive


def _ts(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def test_traceability_insight_reads_delivery_lake(tmp_path):
    output = tmp_path / "output"
    write_rows_to_hive(
        [
            {
                "org": "Acme",
                "repo": "backend",
                "year": 2026,
                "month": 4,
                "collected_at": _ts("2026-04-03T00:00:00"),
                "pr_number": 1,
                "author": "dev",
                "created_at": _ts("2026-04-01T00:00:00"),
                "updated_at": _ts("2026-04-02T00:00:00"),
                "state": "merged",
                "pr_size": 10,
                "task_id": "DEV-1",
                "spec_name": "checkout",
            }
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
                "collected_at": _ts("2026-04-03T00:00:00"),
                "sha": "abc123",
                "author_name": "Dev",
                "author_email": "dev@example.test",
                "committed_at": _ts("2026-04-02T00:00:00"),
                "is_direct_main": True,
                "additions": 5,
                "deletions": 2,
                "changed_files": 1,
                "activity_class": "feature_dev",
                "task_id": None,
                "spec_name": None,
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
                "collected_at": _ts("2026-04-03T00:00:00"),
                "branch": "DEV-2/thing",
                "head_sha": "def456",
                "last_commit_at": _ts("2026-04-02T00:00:00"),
                "last_author": "Dev",
                "ahead_main": 1,
                "behind_main": 0,
                "has_open_pr": False,
                "task_id": "DEV-2",
                "spec_name": None,
            }
        ],
        str(output / "ledger" / "branches"),
        table_name="branches",
    )

    df = run_insight("traceability", output_dir=str(output), org="Acme", repo="backend", days_back=60)

    assert set(df["dataset"]) == {"prs", "commits", "branches"}
    pr_row = df[df["dataset"] == "prs"].iloc[0]
    assert pr_row["task_id_pct"] == 100.0
    assert "prs" in render_dataframe(df)


def test_direct_main_risk_scores_large_untested_commits(tmp_path):
    output = tmp_path / "output"
    write_rows_to_hive(
        [
            {
                "org": "Acme",
                "repo": "backend",
                "year": 2026,
                "month": 4,
                "collected_at": _ts("2026-04-03T00:00:00"),
                "sha": "abc123",
                "author_name": "Dev",
                "author_email": "dev@example.test",
                "committed_at": _ts("2026-04-02T00:00:00"),
                "subject": "feat(auth): direct hotfix",
                "is_direct_main": True,
                "additions": 1200,
                "deletions": 10,
                "changed_files": 3,
                "activity_class": "feature_dev",
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
                "collected_at": _ts("2026-04-03T00:00:00"),
                "sha": "abc123",
                "path": "src/auth/tokens.py",
                "status": "modified",
                "additions": 1200,
                "deletions": 10,
                "top_level_dir": "src",
                "extension": "py",
                "is_test": False,
                "is_generated": False,
                "is_sensitive": True,
            }
        ],
        str(output / "ledger" / "commit_files"),
        table_name="commit_files",
    )

    df = run_insight("direct_main_risk", output_dir=str(output), org="Acme", repo="backend", days_back=60)

    assert df.iloc[0]["risk_score"] == 5
    assert df.iloc[0]["sensitive_files"] == 1
