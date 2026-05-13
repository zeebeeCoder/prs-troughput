import subprocess

import pytest

from pr_metrics import local_git
from pr_metrics.processor import process_commit_ledger_to_rows
from tests.fixtures.git_fixtures import git, make_bare_remote


def clone_remote(tmp_path):
    remote = make_bare_remote(tmp_path)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", str(remote), str(clone)], check=True, capture_output=True, text=True)
    git(clone, "remote", "set-head", "origin", "-a")
    return clone


def test_extract_commits_uses_first_parent_log_with_churn_and_delivery_metadata(tmp_path):
    clone = clone_remote(tmp_path)
    stats = local_git.GitCommandStats()

    commits = local_git.extract_commits(clone, days_back=3650, stats=stats)

    subjects = [commit["commit"]["message"].splitlines()[0] for commit in commits]
    assert subjects[:2] == ["fix: typo", "feat: add login (#42)"]
    first = commits[0]
    assert first["stats"]["additions"] >= 1
    assert first["files"][0]["filename"] == "README.md"
    assert first["_ledger_sources"][0]["source_kind"] == "default_branch"
    assert commits[1]["_ledger_sources"][0]["pr_number"] == 42
    assert stats.commands >= 2


def test_local_commits_preserve_processor_delivery_contract(tmp_path):
    clone = clone_remote(tmp_path)
    commits = local_git.extract_commits(clone, days_back=3650)

    commit_rows, file_rows, link_rows, delivery_rows = process_commit_ledger_to_rows({"backend": commits}, "Acme")

    assert {row["sha"] for row in commit_rows}
    assert {row["path"] for row in file_rows} >= {"README.md", "src/auth.py"}
    assert {row["source_kind"] for row in link_rows} == {"default_branch"}
    modes = {row["delivery_mode"] for row in delivery_rows}
    assert "squash" in modes
    assert "direct_main_candidate" in modes


def test_extract_branches_only_for_open_pr_branches(tmp_path):
    clone = clone_remote(tmp_path)

    rows = local_git.extract_branches(
        clone,
        open_pr_branch_map={
            "feature/demo": {"number": 7, "title": "Demo", "url": "https://example.test/pr/7"},
            "feature/missing": {"number": 8, "title": "Missing", "url": "https://example.test/pr/8"},
        },
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["branch"] == "feature/demo"
    assert row["has_open_pr"] is True
    assert row["pr_number"] == 7
    assert row["ahead_main"] == 1
    assert row["behind_main"] == 0


def test_ensure_fresh_refs_errors_when_refs_are_older_than_window(tmp_path):
    clone = clone_remote(tmp_path)

    with pytest.raises(local_git.StaleRefsError):
        local_git.ensure_fresh_refs(clone, 0)

    local_git.ensure_fresh_refs(clone, 0, allow_stale=True)
