import pandas as pd

from pr_metrics.processor import process_commits_to_rows, process_prs_to_dataframe


def test_process_prs_includes_delivery_queue_fields():
    rows = process_prs_to_dataframe({
        "backend": [
            {
                "number": 42,
                "author": {"login": "dev"},
                "title": "DEV-3871 [spec: print-form] add form",
                "body": "ready",
                "url": "https://example.test/pr/42",
                "createdAt": "2026-04-01T10:00:00Z",
                "updatedAt": "2026-04-02T10:00:00Z",
                "headRefName": "DEV-3871/print-form",
                "baseRefName": "main",
                "headRefOid": "abc123",
                "additions": 10,
                "deletions": 5,
                "reviews": [{"state": "APPROVED", "submittedAt": "2026-04-01T11:00:00Z", "author": {"login": "reviewer"}}],
                "reviewRequests": [{"requestedReviewer": {"login": "next-reviewer"}}],
                "statusCheckRollup": [{"conclusion": "SUCCESS"}],
                "labels": [],
            }
        ]
    }, "Acme")

    row = rows[0]
    assert row["title"] == "DEV-3871 [spec: print-form] add form"
    assert row["updated_at"] == pd.Timestamp("2026-04-02T10:00:00Z")
    assert row["head_ref"] == "DEV-3871/print-form"
    assert row["review_request_count"] == 1
    assert row["requested_reviewers"] == "next-reviewer"
    assert row["approvals_count"] == 1
    assert row["ci_state"] == "success"
    assert row["task_id"] == "DEV-3871"
    assert row["spec_name"] == "print-form"


def test_process_commits_marks_pr_linked_squash_not_direct_main():
    commit = {
        "sha": "abc123",
        "commit": {
            "message": "feat(api): add checkout (#123)\n\nDEV-1000 [spec: checkout]",
            "author": {"name": "Alice", "email": "a@example.test", "date": "2026-04-01T10:00:00Z"},
            "committer": {"name": "Alice", "email": "a@example.test", "date": "2026-04-01T10:10:00Z"},
        },
        "parents": [{"sha": "parent"}],
        "stats": {"additions": 12, "deletions": 3},
        "files": [{"filename": "src/api.py", "status": "modified", "additions": 12, "deletions": 3}],
    }

    commit_rows, file_rows = process_commits_to_rows({"backend": [commit]}, "Acme")

    assert commit_rows[0]["pr_number"] == 123
    assert commit_rows[0]["is_direct_main"] is False
    assert commit_rows[0]["activity_class"] == "feature_dev"
    assert commit_rows[0]["task_id"] == "DEV-1000"
    assert file_rows[0]["top_level_dir"] == "src"
