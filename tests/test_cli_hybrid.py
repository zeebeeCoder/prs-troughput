from pathlib import Path
from types import SimpleNamespace

from pr_metrics import cli


class FakeCache:
    def __init__(self, root):
        self.cache_root = Path(root)
        self.cloned_count = 1
        self.fetched_count = 0

    def ensure_clone(self, org, repo):
        return self.cache_root / org / repo


def test_collect_commit_ledger_routes_hybrid_to_local_git(tmp_path, monkeypatch):
    written = []
    fake_cache = FakeCache(tmp_path / "cache")

    monkeypatch.setattr(cli, "OUTPUT_DIR", str(tmp_path / "lake"))
    monkeypatch.setattr(cli, "CloneCache", lambda root: fake_cache)
    monkeypatch.setattr(cli.local_git, "ensure_fresh_refs", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        cli.local_git,
        "extract_commits",
        lambda *args, **kwargs: [{
            "sha": "abc",
            "parents": [{"sha": "p"}],
            "commit": {
                "author": {"name": "A", "email": "a@example.test", "date": "2026-05-13T00:00:00+00:00"},
                "committer": {"name": "A", "email": "a@example.test", "date": "2026-05-13T00:00:00+00:00"},
                "message": "feat: local (#9)",
            },
            "stats": {"additions": 1, "deletions": 0},
            "files": [{"filename": "src/app.py", "status": "modified", "additions": 1, "deletions": 0}],
            "_ledger_sources": [{"source_kind": "default_branch", "source_id": "default", "pr_number": 9, "branch": None, "evidence": "local"}],
        }],
    )
    monkeypatch.setattr(cli, "write_rows_to_hive", lambda rows, base_dir, table_name: written.append((table_name, rows, base_dir)))

    args = SimpleNamespace(
        ledger_source="hybrid",
        cache_dir=str(tmp_path / "cache"),
        max_concurrency=1,
        days=30,
        allow_stale=False,
        full_body=False,
        skip_commit_files=False,
    )

    cli._collect_commit_ledger(args, "Acme", [{"name": "backend"}])

    tables = {name: rows for name, rows, _base in written}
    assert tables["commits"][0]["sha"] == "abc"
    assert tables["commit_files"][0]["path"] == "src/app.py"
    assert tables["delivery_events"][0]["pr_number"] == 9


def test_cache_command_du_does_not_require_org(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PR_METRICS_CACHE_DIR", str(tmp_path / "cache"))

    cli.main(["cache", "du"])

    assert str(tmp_path / "cache") in capsys.readouterr().out
