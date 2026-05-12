import subprocess
from types import SimpleNamespace

from pr_metrics import github


def test_ensure_gh_authenticated_reports_missing_gh(monkeypatch):
    monkeypatch.setattr(github.shutil, "which", lambda name: None)

    assert "not installed" in github.ensure_gh_authenticated()


def test_ensure_gh_authenticated_reports_auth_error(monkeypatch):
    monkeypatch.setattr(github.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(
        github.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stderr="not logged in", stdout=""),
    )

    message = github.ensure_gh_authenticated()

    assert "not authenticated" in message
    assert "not logged in" in message


def test_ensure_gh_authenticated_returns_none_when_ready(monkeypatch):
    monkeypatch.setattr(github.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(
        github.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stderr="", stdout="ok"),
    )

    assert github.ensure_gh_authenticated() is None


def test_run_gh_command_returns_json(monkeypatch):
    monkeypatch.setattr(
        github.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout='[{"name": "backend"}]'),
    )

    assert github.run_gh_command("gh repo list") == [{"name": "backend"}]


def test_run_gh_command_retries_retryable_errors(monkeypatch):
    calls = {"count": 0}

    def fake_run(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise subprocess.CalledProcessError(1, "gh", stderr="HTTP 502")
        return SimpleNamespace(stdout='{"ok": true}')

    monkeypatch.setattr(github.subprocess, "run", fake_run)
    monkeypatch.setattr(github.time, "sleep", lambda delay: None)

    assert github.run_gh_command("gh api /x", max_retries=2, initial_delay=0) == {"ok": True}
    assert calls["count"] == 2


def test_run_gh_command_returns_empty_list_on_bad_json(monkeypatch):
    monkeypatch.setattr(
        github.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="not json"),
    )

    assert github.run_gh_command("gh bad") == []


def test_get_active_repos_from_search_deduplicates_repo_names(monkeypatch):
    monkeypatch.setattr(
        github,
        "run_gh_command",
        lambda cmd: [
            {"repository": {"name": "backend"}},
            {"repository": {"name": "frontend"}},
            {"repository": {"name": "backend"}},
        ],
    )

    assert github.get_active_repos_from_search("Acme", days_back=7) == [{"name": "backend"}, {"name": "frontend"}]


def test_get_active_repos_from_search_falls_back_to_full_scan(monkeypatch):
    monkeypatch.setattr(github, "run_gh_command", lambda cmd: [])
    monkeypatch.setattr(github, "get_org_repos", lambda org: [{"name": "fallback"}])

    assert github.get_active_repos_from_search("Acme", days_back=7) == [{"name": "fallback"}]


def test_get_repo_prs_filters_by_created_or_updated_date(monkeypatch):
    monkeypatch.setenv("GH_PR_LIMIT", "3")
    seen = {}

    def fake_run(cmd):
        seen["cmd"] = cmd
        return [
            {"number": 1, "createdAt": "1999-01-01T00:00:00Z", "updatedAt": "1999-01-02T00:00:00Z"},
            {"number": 2, "createdAt": "2099-01-01T00:00:00Z", "updatedAt": "2099-01-02T00:00:00Z"},
            {"number": 3, "createdAt": "1999-01-01T00:00:00Z", "updatedAt": "2099-01-02T00:00:00Z"},
        ]

    monkeypatch.setattr(github, "run_gh_command", fake_run)

    prs = github.get_repo_prs("Acme", "backend", days_back=14)

    assert [pr["number"] for pr in prs] == [2, 3]
    assert "--limit 3" in seen["cmd"]
    assert "Acme/backend" in seen["cmd"]


def test_get_repo_branches_collects_branch_snapshot_with_pr_linkage(monkeypatch):
    monkeypatch.setattr(github, "get_default_branch", lambda org, repo: "main")
    monkeypatch.setattr(
        github,
        "get_open_pr_branch_map",
        lambda org, repo: {
            "feature/demo": {
                "number": 7,
                "title": "DEV-7 demo",
                "url": "https://example.test/pr/7",
                "headRefOid": "branch-sha",
            }
        },
    )

    def fake_api(endpoint):
        responses = {
            "repos/Acme/backend/branches/main": {
                "commit": {"sha": "main-sha", "commit": {"author": {"date": "2026-04-01T00:00:00Z", "name": "Main"}}}
            },
            "repos/Acme/backend/branches?per_page=5": [
                {"name": "feature/demo", "commit": {"sha": "branch-sha"}},
            ],
            "repos/Acme/backend/branches/feature%2Fdemo": {
                "commit": {"commit": {"author": {"date": "2026-04-02T00:00:00Z", "name": "Dev"}}}
            },
            "repos/Acme/backend/compare/main...feature%2Fdemo": {"ahead_by": 2, "behind_by": 1},
        }
        return responses[endpoint]

    monkeypatch.setattr(github, "run_gh_api", fake_api)

    rows = github.get_repo_branches("Acme", "backend", limit=5)

    assert rows == [
        {
            "branch": "feature/demo",
            "head_sha": "branch-sha",
            "default_branch": "main",
            "default_head_sha": "main-sha",
            "last_commit_at": "2026-04-02T00:00:00Z",
            "last_author": "Dev",
            "ahead_main": 2,
            "behind_main": 1,
            "has_open_pr": True,
            "pr_number": 7,
            "pr_title": "DEV-7 demo",
            "pr_url": "https://example.test/pr/7",
        }
    ]
