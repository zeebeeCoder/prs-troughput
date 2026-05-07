from datetime import datetime, timezone

from pr_metrics.semantic import classify_delivery_lake_rows, classify_semantic_unit, semantic_unit_from_branch_row, semantic_unit_from_commit_row


def _ts(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def test_commit_receives_multiple_semantic_categories():
    unit = semantic_unit_from_commit_row({
        "org": "Acme",
        "repo": "backend",
        "sha": "abc123",
        "subject": "refactor(auth): simplify token service DEV-7",
        "body": "[spec: auth-cleanup]",
        "conventional_type": "refactor",
        "conventional_scope": "auth",
        "activity_class": "refactor",
        "top_level_dirs": "src,tests",
        "file_exts": "py",
        "task_id": "DEV-7",
        "spec_name": "auth-cleanup",
        "committed_at": _ts("2026-04-01T00:00:00"),
    })

    facts = {(fact.category_namespace, fact.category) for fact in classify_semantic_unit(unit)}

    assert ("work_type", "refactor") in facts
    assert ("quality", "refactoring") in facts
    assert ("quality", "test_coverage") in facts
    assert ("quality", "sensitive_path") in facts
    assert ("traceability", "ticket_linked") in facts
    assert ("traceability", "spec_linked") in facts
    assert ("component", "auth") in facts


def test_branch_roles_classify_environment_and_ticket_wip():
    qa = semantic_unit_from_branch_row({"org": "Acme", "repo": "backend", "branch": "qa", "last_commit_at": _ts("2026-04-01T00:00:00")})
    ticket = semantic_unit_from_branch_row({"org": "Acme", "repo": "backend", "branch": "DEV-123/checkout", "task_id": "DEV-123"})

    qa_facts = {(fact.category_namespace, fact.category) for fact in classify_semantic_unit(qa)}
    ticket_facts = {(fact.category_namespace, fact.category) for fact in classify_semantic_unit(ticket)}

    assert ("branch_role", "environment") in qa_facts
    assert ("traceability", "untraced") in qa_facts
    assert ("branch_role", "ticket_wip") in ticket_facts
    assert ("ticket", "DEV-123") in ticket_facts


def test_classify_delivery_lake_rows_persists_normalized_fact_rows():
    rows = classify_delivery_lake_rows(
        pr_rows=[{
            "org": "Acme",
            "repo": "backend",
            "pr_number": 42,
            "title": "fix: checkout DEV-42",
            "head_ref": "hotfix/checkout",
            "task_id": "DEV-42",
            "updated_at": _ts("2026-04-02T00:00:00"),
        }],
        commit_rows=[{
            "org": "Acme",
            "repo": "backend",
            "sha": "abc123",
            "subject": "docs: update AGENTS.md",
            "activity_class": "agent_tooling",
            "committed_at": _ts("2026-04-02T00:00:00"),
        }],
        branch_rows=[{
            "org": "Acme",
            "repo": "backend",
            "branch": "release/1.0",
            "last_commit_at": _ts("2026-04-02T00:00:00"),
        }],
    )

    keys = {(row["unit_kind"], row["unit_id"], row["category_namespace"], row["category"]) for row in rows}

    assert ("pr", "42", "branch_role", "hotfix") in keys
    assert ("commit", "abc123", "work_type", "docs") in keys
    assert ("commit", "abc123", "work_type", "agent_tooling") in keys
    assert ("branch", "release/1.0", "branch_role", "release") in keys
    assert all(row["taxonomy_version"] == "semantic-taxonomy-v1" for row in rows)
