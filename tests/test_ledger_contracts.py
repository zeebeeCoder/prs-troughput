import os
import subprocess
from datetime import datetime, timezone

from pr_metrics.github import get_repo_pr_commits
from pr_metrics.processor import process_commit_ledger_to_rows


def _ts(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def _git(repo, *args, env=None):
    full_env = os.environ.copy()
    full_env.update(env or {})
    return subprocess.check_output(["git", *args], cwd=repo, text=True, env=full_env).strip()


def _commit(repo, message, when, filename, content):
    path = repo / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    _git(repo, "add", str(path.relative_to(repo)))
    env = {
        "GIT_AUTHOR_DATE": when,
        "GIT_COMMITTER_DATE": when,
    }
    _git(repo, "commit", "-m", message, env=env)
    return _git(repo, "rev-parse", "HEAD")


def _github_commit_from_git(repo, sha, source):
    subject = _git(repo, "show", "-s", "--format=%s", sha)
    body = _git(repo, "show", "-s", "--format=%b", sha)
    author_name = _git(repo, "show", "-s", "--format=%an", sha)
    author_email = _git(repo, "show", "-s", "--format=%ae", sha)
    authored_at = _git(repo, "show", "-s", "--format=%aI", sha)
    committer_name = _git(repo, "show", "-s", "--format=%cn", sha)
    committer_email = _git(repo, "show", "-s", "--format=%ce", sha)
    committed_at = _git(repo, "show", "-s", "--format=%cI", sha)
    parents = _git(repo, "show", "-s", "--format=%P", sha).split()
    numstat = _git(repo, "show", "--numstat", "--format=", sha).splitlines()
    files = []
    additions = deletions = 0
    for line in numstat:
        added, deleted, path = line.split("\t")
        add_value = 0 if added == "-" else int(added)
        delete_value = 0 if deleted == "-" else int(deleted)
        additions += add_value
        deletions += delete_value
        files.append({"filename": path, "status": "modified", "additions": add_value, "deletions": delete_value})
    return {
        "sha": sha,
        "commit": {
            "message": subject + (f"\n\n{body}" if body else ""),
            "author": {"name": author_name, "email": author_email, "date": authored_at},
            "committer": {"name": committer_name, "email": committer_email, "date": committed_at},
        },
        "parents": [{"sha": parent} for parent in parents],
        "stats": {"additions": additions, "deletions": deletions},
        "files": files,
        "_ledger_sources": [source],
    }


def _ledger_fixture_repo(tmp_path):
    repo = tmp_path / "ledger-fixture"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test Dev")
    _git(repo, "config", "user.email", "dev@example.test")
    _commit(repo, "chore: initial", "2026-04-01T00:00:00Z", "README.md", "base\n")

    _git(repo, "checkout", "-b", "feature/squash")
    a_sha = _commit(repo, "feat: branch part 1", "2026-04-02T00:00:00Z", "src/a.py", "a = 1\n")
    b_sha = _commit(repo, "fix: branch part 2", "2026-04-03T00:00:00Z", "src/b.py", "b = 1\n")
    c_sha = _commit(repo, "test: branch part 3", "2026-04-04T00:00:00Z", "tests/test_c.py", "def test_c(): pass\n")

    _git(repo, "checkout", "master")
    _git(repo, "merge", "--squash", "feature/squash")
    env = {"GIT_AUTHOR_DATE": "2026-04-05T00:00:00Z", "GIT_COMMITTER_DATE": "2026-04-05T00:00:00Z"}
    _git(repo, "commit", "-m", "feat: squashed feature (#7)", env=env)
    squash_sha = _git(repo, "rev-parse", "HEAD")
    direct_sha = _commit(repo, "chore: direct config tweak", "2026-04-06T00:00:00Z", "config.yml", "x: 1\n")

    _git(repo, "checkout", "-b", "feature/no-pr")
    x_sha = _commit(repo, "feat: invisible WIP", "2026-04-07T00:00:00Z", "src/x.py", "x = 1\n")
    y_sha = _commit(repo, "fix: invisible WIP", "2026-04-08T00:00:00Z", "src/y.py", "y = 1\n")

    return repo, {
        "branch_pr": [a_sha, b_sha, c_sha],
        "squash": squash_sha,
        "direct": direct_sha,
        "invisible": [x_sha, y_sha],
    }


def test_foundational_ledger_contract_squash_direct_and_branch_wip(tmp_path):
    repo, shas = _ledger_fixture_repo(tmp_path)
    commits = []
    for sha in shas["branch_pr"]:
        commits.append(_github_commit_from_git(repo, sha, {
            "source_kind": "pr_commit",
            "source_id": "pr/7",
            "pr_number": 7,
            "branch": "feature/squash",
            "evidence": "pulls/7/commits",
        }))
    commits.append(_github_commit_from_git(repo, shas["squash"], {
        "source_kind": "default_branch",
        "source_id": "master",
        "pr_number": 7,
        "evidence": "subject_marker",
    }))
    commits.append(_github_commit_from_git(repo, shas["direct"], {
        "source_kind": "default_branch",
        "source_id": "master",
        "evidence": "default_branch_scan",
    }))
    for sha in shas["invisible"]:
        commits.append(_github_commit_from_git(repo, sha, {
            "source_kind": "branch_commit",
            "source_id": "branch/feature/no-pr",
            "branch": "feature/no-pr",
            "evidence": "compare/master...feature/no-pr",
        }))

    commit_rows, file_rows, link_rows, delivery_rows = process_commit_ledger_to_rows({"backend": commits}, "Acme")

    assert {row["sha"] for row in commit_rows} == set(shas["branch_pr"] + [shas["squash"], shas["direct"]] + shas["invisible"])
    assert len(commit_rows) == 7
    assert len(file_rows) >= 7

    links_by_sha = {row["sha"]: row for row in link_rows}
    assert all(links_by_sha[sha]["source_kind"] == "pr_commit" for sha in shas["branch_pr"])
    assert all(links_by_sha[sha]["pr_number"] == 7 for sha in shas["branch_pr"])
    assert all(links_by_sha[sha]["source_kind"] == "branch_commit" for sha in shas["invisible"])

    rows_by_sha = {row["sha"]: row for row in commit_rows}
    assert rows_by_sha[shas["squash"]]["is_direct_main"] is False
    assert rows_by_sha[shas["squash"]]["on_main"] is True
    assert rows_by_sha[shas["direct"]]["is_direct_main"] is True
    assert all(rows_by_sha[sha]["on_main"] is False for sha in shas["invisible"])

    delivery_by_sha = {row["delivery_sha"]: row for row in delivery_rows}
    assert set(delivery_by_sha) == {shas["squash"], shas["direct"]}
    assert delivery_by_sha[shas["squash"]]["delivery_mode"] == "squash"
    assert delivery_by_sha[shas["squash"]]["pr_number"] == 7
    assert delivery_by_sha[shas["direct"]]["delivery_mode"] == "direct_main_candidate"


def test_pr_commit_api_contract_survives_deleted_branch(monkeypatch):
    monkeypatch.setattr(
        "pr_metrics.github.get_repo_prs",
        lambda org, repo, days_back: [{"number": 8, "headRefName": "deleted/branch", "title": "feat: deleted branch"}],
    )

    def fake_api(endpoint):
        if endpoint == "repos/Acme/backend/pulls/8/commits?per_page=100":
            return [
                {"sha": "p1", "commit": {"message": "feat: preserved 1", "committer": {"date": "2026-04-01T00:00:00Z"}}},
                {"sha": "p2", "commit": {"message": "fix: preserved 2", "committer": {"date": "2026-04-02T00:00:00Z"}}},
            ]
        if endpoint == "repos/Acme/backend/commits/p1":
            return {"sha": "p1", "commit": {"message": "feat: preserved 1", "committer": {"date": "2026-04-01T00:00:00Z"}}, "parents": [{"sha": "base"}], "files": []}
        if endpoint == "repos/Acme/backend/commits/p2":
            return {"sha": "p2", "commit": {"message": "fix: preserved 2", "committer": {"date": "2026-04-02T00:00:00Z"}}, "parents": [{"sha": "p1"}], "files": []}
        raise AssertionError(endpoint)

    monkeypatch.setattr("pr_metrics.github.run_gh_api", fake_api)

    commits = get_repo_pr_commits("Acme", "backend", days_back=30, pr_limit=10, commit_limit=100, include_files=True)

    assert [commit["sha"] for commit in commits] == ["p1", "p2"]
    assert all(commit["_ledger_sources"][0]["source_kind"] == "pr_commit" for commit in commits)
    assert all(commit["_ledger_sources"][0]["pr_number"] == 8 for commit in commits)
    assert all(commit["_ledger_sources"][0]["branch"] == "deleted/branch" for commit in commits)
