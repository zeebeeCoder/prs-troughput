import subprocess
from datetime import datetime, timezone

from pr_metrics.storage import write_rows_to_hive
from pr_metrics.validation import validate_local_repo


def _ts(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def test_validate_local_repo_compares_commits_and_branches_read_only(tmp_path):
    repo = tmp_path / "local"
    repo.mkdir()
    _git(repo, "init", "-b", "master")
    _git(repo, "config", "user.email", "dev@example.test")
    _git(repo, "config", "user.name", "Dev")
    (repo / "app.py").write_text("print('one')\n")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "feat: first")
    base_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-b", "feature/test")
    (repo / "app.py").write_text("print('one')\nprint('two')\n")
    _git(repo, "commit", "-am", "fix: branch work")
    branch_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "master")
    # Create local remote-tracking refs without adding/fetching a real remote.
    _git(repo, "update-ref", "refs/remotes/origin/master", base_sha)
    _git(repo, "update-ref", "refs/remotes/origin/feature/test", branch_sha)

    output = tmp_path / "output"
    write_rows_to_hive(
        [
            {
                "org": "Acme",
                "repo": "backend",
                "year": 2026,
                "month": 4,
                "collected_at": _ts("2026-04-03T00:00:00"),
                "sha": branch_sha,
                "author_name": "Dev",
                "author_email": "dev@example.test",
                "committed_at": _ts("2026-04-02T00:00:00"),
                "subject": "fix: branch work",
                "parent_count": 1,
                "is_direct_main": True,
                "additions": 1,
                "deletions": 0,
                "changed_files": 1,
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
                "collected_at": _ts("2026-04-03T00:00:00"),
                "branch": "feature/test",
                "head_sha": branch_sha,
                "default_branch": "master",
                "default_head_sha": base_sha,
                "last_commit_at": _ts("2026-04-02T00:00:00"),
                "last_author": "Dev",
                "ahead_main": 1,
                "behind_main": 0,
                "has_open_pr": False,
            }
        ],
        str(output / "ledger" / "branches"),
        table_name="branches",
    )

    result = validate_local_repo(str(repo), "Acme", "backend", output_dir=str(output), days_back=60)

    assert result.commit_summary.iloc[0]["accuracy_pct"] == 100.0
    assert result.branch_summary.iloc[0]["accuracy_pct"] == 100.0
    assert result.commit_mismatches.empty
    assert result.branch_mismatches.empty
