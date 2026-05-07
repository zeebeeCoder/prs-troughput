from datetime import datetime, timezone

from pr_metrics.insights import create_delivery_lake_views, render_dataframe, run_insight
from pr_metrics.storage import write_rows_to_hive


def _ts(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def test_semantic_embedding_coverage_and_duckdb_similarity_query(tmp_path):
    output = tmp_path / "output"
    write_rows_to_hive(
        [
            {
                "org": "Acme",
                "repo": "backend",
                "year": 2026,
                "month": 4,
                "unit_kind": "commit",
                "unit_id": "refactor-sha",
                "text_hash": "h1",
                "text": "refactor service boundaries",
                "embedding_model": "fake-embed",
                "embedding_dimensions": 3,
                "embedding": [1.0, 0.0, 0.0],
                "embedded_at": _ts("2026-04-03T00:00:00"),
                "observed_at": _ts("2026-04-02T00:00:00"),
                "tokens": 5,
                "error": None,
            },
            {
                "org": "Acme",
                "repo": "backend",
                "year": 2026,
                "month": 4,
                "unit_kind": "commit",
                "unit_id": "feature-sha",
                "text_hash": "h2",
                "text": "add checkout feature",
                "embedding_model": "fake-embed",
                "embedding_dimensions": 3,
                "embedding": [0.0, 1.0, 0.0],
                "embedded_at": _ts("2026-04-03T00:00:00"),
                "observed_at": _ts("2026-04-02T00:00:00"),
                "tokens": 5,
                "error": None,
            },
        ],
        str(output / "ledger" / "semantic_embeddings"),
        table_name="semantic_embeddings",
    )

    coverage = run_insight("semantic_embedding_coverage", output_dir=str(output), org="Acme", repo="backend", days_back=60)
    assert coverage.iloc[0]["embedded_units"] == 2
    assert coverage.iloc[0]["embedded_pct"] == 100.0

    con, available = create_delivery_lake_views(output_dir=str(output), org="Acme", repo="backend", days_back=60)
    try:
        assert "semantic_embeddings_latest" in available
        nearest = con.execute("""
            SELECT unit_id, list_cosine_similarity(embedding, [1.0, 0.0, 0.0]) AS score
            FROM semantic_embeddings_latest
            WHERE unit_kind = 'commit'
            ORDER BY score DESC
        """).fetchdf()
    finally:
        con.close()

    assert list(nearest["unit_id"]) == ["refactor-sha", "feature-sha"]
    assert nearest.iloc[0]["score"] == 1.0


def test_active_repos_uses_commit_branch_and_delivery_lake_without_prs(tmp_path):
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
                "source_kinds": "default_branch",
                "is_direct_main": True,
                "additions": 5,
                "deletions": 2,
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
                "branch": "DEV-1/feature",
                "head_sha": "def456",
                "last_commit_at": _ts("2026-04-03T00:00:00"),
                "last_author": "Dev",
                "ahead_main": 2,
                "behind_main": 0,
                "has_open_pr": False,
            }
        ],
        str(output / "ledger" / "branches"),
        table_name="branches",
    )

    df = run_insight("active_repos", output_dir=str(output), org="Acme", repo="backend", days_back=60)

    assert len(df) == 1
    row = df.iloc[0]
    assert row["repo"] == "backend"
    assert row["pr_events"] == 0
    assert row["commit_events"] == 1
    assert row["delivery_events"] == 1
    assert row["active_branches"] == 1
    assert row["local_lake_status"] == "multi_source_lake"
    assert "commits" in row["activity_sources"]
    assert "branches" in row["activity_sources"]


def test_repo_lake_coverage_exposes_missing_dataset_shapes(tmp_path):
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
                "state": "open",
                "pr_size": 10,
            }
        ],
        str(output / "data"),
        table_name="pr_data",
    )
    write_rows_to_hive(
        [
            {
                "org": "Acme",
                "repo": "ledger-only",
                "year": 2026,
                "month": 4,
                "collected_at": _ts("2026-04-03T00:00:00"),
                "sha": "abc123",
                "author_email": "dev@example.test",
                "committed_at": _ts("2026-04-02T00:00:00"),
                "source_kinds": "default_branch",
                "is_direct_main": True,
            }
        ],
        str(output / "ledger" / "commits"),
        table_name="commits",
    )

    df = run_insight("repo_lake_coverage", output_dir=str(output), org="Acme", days_back=60)

    by_repo = {row["repo"]: row for _, row in df.iterrows()}
    assert by_repo["backend"]["has_pr_data"] is True
    assert by_repo["backend"]["has_commit_data"] is False
    assert by_repo["ledger-only"]["has_pr_data"] is False
    assert by_repo["ledger-only"]["has_commit_data"] is True


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


def test_invisible_wip_excludes_semantic_environment_branches(tmp_path):
    output = tmp_path / "output"
    branch_rows = [
        {
            "org": "Acme",
            "repo": "backend",
            "year": 2026,
            "month": 4,
            "collected_at": _ts("2026-04-03T00:00:00"),
            "branch": "qa",
            "head_sha": "qa1",
            "last_commit_at": _ts("2026-04-02T00:00:00"),
            "last_author": "Ops",
            "ahead_main": 3,
            "behind_main": 0,
            "has_open_pr": False,
        },
        {
            "org": "Acme",
            "repo": "backend",
            "year": 2026,
            "month": 4,
            "collected_at": _ts("2026-04-03T00:00:00"),
            "branch": "DEV-7/feature",
            "head_sha": "dev7",
            "last_commit_at": _ts("2026-04-02T00:00:00"),
            "last_author": "Dev",
            "ahead_main": 2,
            "behind_main": 0,
            "has_open_pr": False,
            "task_id": "DEV-7",
        },
    ]
    write_rows_to_hive(branch_rows, str(output / "ledger" / "branches"), table_name="branches")
    write_rows_to_hive(
        [
            {
                "org": "Acme",
                "repo": "backend",
                "year": 2026,
                "month": 4,
                "unit_kind": "branch",
                "unit_id": "qa",
                "category_namespace": "branch_role",
                "category": "environment",
                "score": 1.0,
                "confidence": "high",
                "source": "rule",
                "evidence": "branch=qa",
                "classifier_version": "deterministic-rules-v1",
                "taxonomy_version": "semantic-taxonomy-v1",
                "embedding_model": "none",
                "classified_at": _ts("2026-04-03T00:00:00"),
                "observed_at": _ts("2026-04-02T00:00:00"),
            },
            {
                "org": "Acme",
                "repo": "backend",
                "year": 2026,
                "month": 4,
                "unit_kind": "branch",
                "unit_id": "DEV-7/feature",
                "category_namespace": "branch_role",
                "category": "ticket_wip",
                "score": 0.9,
                "confidence": "high",
                "source": "rule",
                "evidence": "branch=DEV-7/feature",
                "classifier_version": "deterministic-rules-v1",
                "taxonomy_version": "semantic-taxonomy-v1",
                "embedding_model": "none",
                "classified_at": _ts("2026-04-03T00:00:00"),
                "observed_at": _ts("2026-04-02T00:00:00"),
            },
        ],
        str(output / "ledger" / "semantic_categories"),
        table_name="semantic_categories",
    )

    df = run_insight("invisible_wip", output_dir=str(output), org="Acme", repo="backend", days_back=60)

    assert list(df["branch"]) == ["DEV-7/feature"]
    assert df.iloc[0]["branch_roles"] == "ticket_wip"


def test_refactoring_activity_uses_semantic_categories(tmp_path):
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
                "source_kinds": "pr_commit",
                "is_direct_main": False,
                "additions": 5,
                "deletions": 2,
                "task_id": "DEV-7",
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
                "pr_number": 7,
                "author": "dev",
                "created_at": _ts("2026-04-01T00:00:00"),
                "updated_at": _ts("2026-04-02T00:00:00"),
                "merged_at": _ts("2026-04-02T00:00:00"),
                "state": "merged",
                "pr_size": 10,
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
                "branch": "DEV-8/refactor",
                "head_sha": "def456",
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
    write_rows_to_hive(
        [
            {
                "org": "Acme",
                "repo": "backend",
                "year": 2026,
                "month": 4,
                "unit_kind": "commit",
                "unit_id": "abc123",
                "category_namespace": "work_type",
                "category": "refactor",
                "score": 1.0,
                "confidence": "high",
                "source": "rule",
                "evidence": "conventional_type=refactor",
                "classifier_version": "deterministic-rules-v1",
                "taxonomy_version": "semantic-taxonomy-v1",
                "embedding_model": "none",
                "classified_at": _ts("2026-04-03T00:00:00"),
                "observed_at": _ts("2026-04-02T00:00:00"),
            }
        ],
        str(output / "ledger" / "semantic_categories"),
        table_name="semantic_categories",
    )

    df = run_insight("refactoring_activity", output_dir=str(output), org="Acme", repo="backend", days_back=60)

    assert len(df) == 1
    assert df.iloc[0]["unit_kind"] == "commit"
    assert df.iloc[0]["churn"] == 7
    assert df.iloc[0]["task_ids"] == "DEV-7"


def test_untraced_units_lists_actionable_unit_rows(tmp_path):
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
                "title": "feat: no ticket",
                "url": "https://example.test/pr/1",
                "created_at": _ts("2026-04-01T00:00:00"),
                "updated_at": _ts("2026-04-02T00:00:00"),
                "state": "open",
                "pr_size": 100,
                "changed_files": 3,
                "head_sha": "pr1",
                "task_id": None,
                "spec_name": None,
            },
            {
                "org": "Acme",
                "repo": "backend",
                "year": 2026,
                "month": 4,
                "collected_at": _ts("2026-04-03T00:00:00"),
                "pr_number": 2,
                "author": "dev",
                "title": "feat: ticketed",
                "url": "https://example.test/pr/2",
                "created_at": _ts("2026-04-01T00:00:00"),
                "updated_at": _ts("2026-04-02T00:00:00"),
                "state": "open",
                "pr_size": 10,
                "changed_files": 1,
                "head_sha": "pr2",
                "task_id": "DEV-2",
                "spec_name": None,
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
                "collected_at": _ts("2026-04-03T00:00:00"),
                "sha": "abc123",
                "author_name": "Dev",
                "author_email": "dev@example.test",
                "committed_at": _ts("2026-04-02T00:00:00"),
                "subject": "fix: no ticket",
                "source_kinds": "default_branch",
                "is_direct_main": True,
                "additions": 5,
                "deletions": 2,
                "changed_files": 1,
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
                "branch": "qa",
                "head_sha": "qa1",
                "last_commit_at": _ts("2026-04-02T00:00:00"),
                "last_author": "Ops",
                "ahead_main": 3,
                "behind_main": 0,
                "has_open_pr": False,
                "pr_url": None,
                "task_id": None,
                "spec_name": None,
            }
        ],
        str(output / "ledger" / "branches"),
        table_name="branches",
    )

    df = run_insight("untraced_units", output_dir=str(output), org="Acme", repo="backend", days_back=60)

    assert set(df["unit_kind"]) == {"pr", "commit", "branch"}
    assert "2" not in set(df["unit_id"])
    pr_row = df[df["unit_kind"] == "pr"].iloc[0]
    assert pr_row["summary"] == "feat: no ticket"
    assert pr_row["url"] == "https://example.test/pr/1"


def test_traceability_breakdown_groups_by_semantic_work_type(tmp_path):
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
                "title": "feat: traced",
                "url": "https://example.test/pr/1",
                "created_at": _ts("2026-04-01T00:00:00"),
                "updated_at": _ts("2026-04-02T00:00:00"),
                "state": "open",
                "pr_size": 10,
                "changed_files": 1,
                "task_id": "DEV-1",
                "spec_name": None,
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
                "subject": "refactor: no ticket",
                "source_kinds": "pr_commit",
                "is_direct_main": False,
                "additions": 5,
                "deletions": 2,
                "changed_files": 1,
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
                "branch": "DEV-2/feature",
                "head_sha": "b1",
                "last_commit_at": _ts("2026-04-02T00:00:00"),
                "last_author": "Dev",
                "ahead_main": 2,
                "behind_main": 0,
                "has_open_pr": False,
                "task_id": "DEV-2",
                "spec_name": None,
            }
        ],
        str(output / "ledger" / "branches"),
        table_name="branches",
    )
    write_rows_to_hive(
        [
            {
                "org": "Acme",
                "repo": "backend",
                "year": 2026,
                "month": 4,
                "unit_kind": "commit",
                "unit_id": "abc123",
                "category_namespace": "work_type",
                "category": "refactor",
                "score": 1.0,
                "confidence": "high",
                "source": "rule",
                "evidence": "conventional_type=refactor",
                "classifier_version": "deterministic-rules-v1",
                "taxonomy_version": "semantic-taxonomy-v1",
                "embedding_model": "none",
                "classified_at": _ts("2026-04-03T00:00:00"),
                "observed_at": _ts("2026-04-02T00:00:00"),
            },
            {
                "org": "Acme",
                "repo": "backend",
                "year": 2026,
                "month": 4,
                "unit_kind": "branch",
                "unit_id": "DEV-2/feature",
                "category_namespace": "branch_role",
                "category": "ticket_wip",
                "score": 1.0,
                "confidence": "high",
                "source": "rule",
                "evidence": "branch=DEV-2/feature",
                "classifier_version": "deterministic-rules-v1",
                "taxonomy_version": "semantic-taxonomy-v1",
                "embedding_model": "none",
                "classified_at": _ts("2026-04-03T00:00:00"),
                "observed_at": _ts("2026-04-02T00:00:00"),
            },
        ],
        str(output / "ledger" / "semantic_categories"),
        table_name="semantic_categories",
    )

    df = run_insight("traceability_breakdown", output_dir=str(output), org="Acme", repo="backend", days_back=60)

    refactor_row = df[df["semantic_group"] == "refactor"].iloc[0]
    assert refactor_row["unit_kind"] == "commit"
    assert refactor_row["untraced_units"] == 1
    assert refactor_row["untraced_churn"] == 7
    ticket_row = df[df["semantic_group"] == "ticket_wip"].iloc[0]
    assert ticket_row["traced_units"] == 1
    assert ticket_row["traced_pct"] == 100.0


def test_kinetics_weekly_uses_explicit_commit_and_delivery_grains(tmp_path):
    output = tmp_path / "output"
    write_rows_to_hive(
        [
            {
                "org": "Acme",
                "repo": "backend",
                "year": 2026,
                "month": 4,
                "collected_at": _ts("2026-04-06T00:00:00"),
                "pr_number": 7,
                "author": "dev",
                "created_at": _ts("2026-04-02T00:00:00"),
                "updated_at": _ts("2026-04-05T00:00:00"),
                "state": "merged",
                "pr_size": 20,
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
                "collected_at": _ts("2026-04-06T00:00:00"),
                "sha": "a1",
                "author_email": "dev@example.test",
                "committed_at": _ts("2026-04-02T00:00:00"),
                "source_kinds": "pr_commit",
                "is_direct_main": False,
                "additions": 5,
                "deletions": 1,
            },
            {
                "org": "Acme",
                "repo": "backend",
                "year": 2026,
                "month": 4,
                "collected_at": _ts("2026-04-06T00:00:00"),
                "sha": "s1",
                "author_email": "dev@example.test",
                "committed_at": _ts("2026-04-05T00:00:00"),
                "source_kinds": "default_branch",
                "is_direct_main": False,
                "additions": 5,
                "deletions": 1,
            },
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
                "collected_at": _ts("2026-04-06T00:00:00"),
                "delivery_sha": "s1",
                "delivered_at": _ts("2026-04-05T00:00:00"),
                "delivery_mode": "squash",
                "pr_number": 7,
                "evidence": "subject_marker",
            }
        ],
        str(output / "ledger" / "delivery_events"),
        table_name="delivery_events",
    )

    df = run_insight("kinetics_weekly", output_dir=str(output), org="Acme", repo="backend", days_back=60)

    row = df.iloc[0]
    assert row["authored_commit_events"] == 2
    assert row["default_branch_commit_events"] == 1
    assert row["delivered_commit_events"] == 1
    assert row["direct_main_candidates"] == 0
    assert "direct_main_delivery_pct" in df.columns


def test_kinetics_weekly_synthesizes_delivery_events_for_legacy_commit_lake(tmp_path):
    output = tmp_path / "output"
    write_rows_to_hive(
        [
            {
                "org": "Acme",
                "repo": "backend",
                "year": 2026,
                "month": 4,
                "collected_at": _ts("2026-04-06T00:00:00"),
                "pr_number": 1,
                "author": "dev",
                "created_at": _ts("2026-04-02T00:00:00"),
                "updated_at": _ts("2026-04-02T00:00:00"),
                "state": "merged",
                "pr_size": 10,
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
                "collected_at": _ts("2026-04-06T00:00:00"),
                "sha": "legacy1",
                "author_email": "dev@example.test",
                "committed_at": _ts("2026-04-02T00:00:00"),
                "on_main": True,
                "is_direct_main": True,
                "parent_count": 1,
                "pr_number": None,
                "additions": 1,
                "deletions": 1,
            }
        ],
        str(output / "ledger" / "commits"),
        table_name="commits",
    )

    df = run_insight("kinetics_weekly", output_dir=str(output), org="Acme", repo="backend", days_back=60)

    row = df.iloc[0]
    assert row["authored_commit_events"] == 1
    assert row["delivered_commit_events"] == 1
    assert row["direct_main_candidates"] == 1


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
