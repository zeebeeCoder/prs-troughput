import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from pr_metrics import cli


def test_main_lists_insights(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["pr-metrics", "--list-insights"])

    cli.main()

    output = capsys.readouterr().out
    assert "active_repos" in output
    assert "traceability" in output


def test_main_requires_org_with_cli_error(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["pr-metrics"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 2
    assert "GitHub organization not specified" in capsys.readouterr().err


def test_main_runs_named_insight(monkeypatch, capsys):
    seen = {}

    def fake_run_insight(name, **kwargs):
        seen["name"] = name
        seen.update(kwargs)
        return pd.DataFrame([{"answer": 42}])

    monkeypatch.setattr(cli, "run_insight", fake_run_insight)
    monkeypatch.setattr(cli, "render_dataframe", lambda df, fmt: f"rendered {fmt} {df.iloc[0]['answer']}")
    monkeypatch.setattr(sys, "argv", ["pr-metrics", "--org", "Acme", "--repo", "backend", "--days", "7", "--insight", "traceability", "--format", "json"])

    cli.main()

    assert seen == {
        "name": "traceability",
        "output_dir": "output",
        "org": "Acme",
        "repo": "backend",
        "days_back": 7,
    }
    assert "rendered json 42" in capsys.readouterr().out


def test_main_uses_output_dir_argument_for_insights(tmp_path, monkeypatch, capsys):
    seen = {}
    lake_dir = tmp_path / "shared-lake"

    def fake_run_insight(name, **kwargs):
        seen.update(kwargs)
        return pd.DataFrame([{"answer": 42}])

    monkeypatch.setattr(cli, "OUTPUT_DIR", "output")
    monkeypatch.setattr(cli, "run_insight", fake_run_insight)
    monkeypatch.setattr(cli, "render_dataframe", lambda df, fmt: "rendered")
    monkeypatch.setattr(sys, "argv", [
        "pr-metrics", "--org", "Acme", "--insight", "active_repos", "--output-dir", str(lake_dir)
    ])

    cli.main()

    assert seen["output_dir"] == str(lake_dir)
    assert "rendered" in capsys.readouterr().out


def test_apply_output_dir_uses_environment(monkeypatch):
    monkeypatch.setattr(cli, "OUTPUT_DIR", "output")
    monkeypatch.setenv("PR_METRICS_OUTPUT_DIR", "/tmp/pr-metrics-lake")

    cli._apply_output_dir(SimpleNamespace(output_dir=None))

    assert cli.OUTPUT_DIR == "/tmp/pr-metrics-lake"


def test_print_skill_bundle_includes_scripts(tmp_path, monkeypatch, capsys):
    skill_dir = tmp_path / "skills" / "delivery-insights"
    docs_dir = tmp_path / "docs"
    views_dir = tmp_path / "views"
    scripts_dir = skill_dir / "scripts"
    for directory in (skill_dir, docs_dir, views_dir, scripts_dir):
        directory.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text("# Skill\n")
    (skill_dir / "INSTALL.md").write_text("# Install\n")
    (skill_dir / "VALIDATION.md").write_text("# Validation\n")
    (docs_dir / "data-contract.md").write_text("# Contract\n")
    (docs_dir / "analysis-playbook.md").write_text("# Playbook\n")
    (views_dir / "setup.sql").write_text("SELECT 1;\n")
    (scripts_dir / "temporal_heatmap.py").write_text("print('heatmap')\n")
    (scripts_dir / "README.md").write_text("# Scripts\n")
    monkeypatch.setattr(cli, "_repo_root", lambda: tmp_path)

    cli._handle_print_skill_bundle()

    output = capsys.readouterr().out
    assert 'mkdir -p "$TARGET/docs" "$TARGET/views" "$TARGET/scripts"' in output
    assert 'cat > "$TARGET/scripts/temporal_heatmap.py"' in output
    assert "DELIVERY_INSIGHTS_EOF_" in output


def test_select_repos_uses_explicit_repo_list():
    args = SimpleNamespace(repo="backend, frontend ,,", full_scan=False, days=14)

    assert cli._select_repos(args, "Acme") == [{"name": "backend"}, {"name": "frontend"}]


def test_select_repos_uses_full_scan(monkeypatch):
    monkeypatch.setattr(cli, "get_org_repos", lambda org: [{"name": "backend"}])
    args = SimpleNamespace(repo=None, full_scan=True, days=14)

    assert cli._select_repos(args, "Acme") == [{"name": "backend"}]


def test_select_repos_uses_active_search(monkeypatch):
    monkeypatch.setattr(cli, "get_active_repos_from_search", lambda org, days: [{"name": "active"}])
    args = SimpleNamespace(repo=None, full_scan=False, days=30)

    assert cli._select_repos(args, "Acme") == [{"name": "active"}]


def test_collect_prs_filters_low_activity_repos_and_persists(tmp_path, monkeypatch):
    written = {}
    rows = [
        {"repo": "active", "state": "merged", "pr_size": 10, "time_to_merge_hours": 2.0, "author": "alice"},
        {"repo": "active", "state": "open", "pr_size": 5, "time_to_merge_hours": None, "author": "bob"},
        {"repo": "quiet", "state": "merged", "pr_size": 1, "time_to_merge_hours": 1.0, "author": "alice"},
    ]

    monkeypatch.setattr(cli, "OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr(cli, "get_repo_prs", lambda org, repo, days: [{"repo": repo}])
    monkeypatch.setattr(cli, "process_prs_to_dataframe", lambda all_prs, org: rows)
    monkeypatch.setattr(cli, "write_to_hive", lambda pr_rows, org, base_dir: written.update({"rows": pr_rows, "org": org, "base_dir": base_dir}))
    args = SimpleNamespace(days=14, min_prs=2, repo=None)

    result = cli._collect_prs(args, "Acme", [{"name": "active"}, {"name": "quiet"}])

    assert [row["repo"] for row in result] == ["active", "active"]
    assert [row["repo"] for row in written["rows"]] == ["active", "active"]
    assert written["org"] == "acme"
    assert list((tmp_path / "output").glob("pr_data_acme_*.csv"))


def test_collect_ledger_respects_include_flags(tmp_path, monkeypatch):
    calls = []
    repos = [{"name": "backend"}]
    monkeypatch.setattr(cli, "OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr(cli, "_collect_commit_ledger", lambda args, org, selected: calls.append(("commits", org, selected)))
    monkeypatch.setattr(cli, "_collect_branch_ledger", lambda args, org, selected: calls.append(("branches", org, selected)))

    cli._collect_ledger(SimpleNamespace(include_ledger=False, include_commits=False, include_branches=False, classify_semantics=False), "Acme", repos)
    assert calls == []

    cli._collect_ledger(SimpleNamespace(include_ledger=False, include_commits=True, include_branches=False, classify_semantics=False), "Acme", repos)
    assert calls == [("commits", "Acme", repos)]

    cli._collect_ledger(SimpleNamespace(include_ledger=True, include_commits=False, include_branches=False, classify_semantics=False), "Acme", repos)
    assert calls[-2:] == [("commits", "Acme", repos), ("branches", "Acme", repos)]


def test_collect_ledger_runs_semantic_classifier_when_requested(tmp_path, monkeypatch):
    calls = []
    repos = [{"name": "backend"}]
    monkeypatch.setattr(cli, "OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr(cli, "_classify_semantics", lambda args, org: calls.append(("semantics", org)))

    cli._collect_ledger(SimpleNamespace(include_ledger=False, include_commits=False, include_branches=False, classify_semantics=True), "Acme", repos)

    assert calls == [("semantics", "Acme")]


def test_main_collection_delegates_to_collectors(monkeypatch):
    calls = []
    repos = [{"name": "backend"}]

    monkeypatch.setattr(cli, "ensure_gh_authenticated", lambda: None)
    monkeypatch.setattr(cli, "_select_repos", lambda args, org: repos)
    monkeypatch.setattr(cli, "_collect_prs", lambda args, org, selected: calls.append(("prs", org, selected)))
    monkeypatch.setattr(cli, "_collect_ledger", lambda args, org, selected: calls.append(("ledger", org, selected)))
    monkeypatch.setattr(sys, "argv", ["pr-metrics", "--org", "Acme", "--repo", "backend"])

    cli.main()

    assert calls == [("prs", "Acme", repos), ("ledger", "Acme", repos)]
