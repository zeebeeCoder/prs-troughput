from datetime import datetime, timezone

from pr_metrics.semantic import TAXONOMY_ENTRIES, classify_delivery_lake_rows, classify_semantic_unit, embed_semantic_units, semantic_unit_from_branch_row, semantic_unit_from_commit_row


class FakeEmbeddingClient:
    def embed(self, texts):
        return [type("EmbeddingResult", (), {"embedding": self._vector(text)})() for text in texts]

    def _vector(self, text):
        lowered = text.lower()
        refactor = "refactor" in lowered or "restructuring" in lowered or "simplification" in lowered or "simplify" in lowered
        oracle = "oracle" in lowered or "daily card" in lowered
        if refactor or oracle:
            return [1.0 if refactor else 0.0, 1.0 if oracle else 0.0, 0.0]
        return [0.0, 0.0, 1.0]


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


def test_hybrid_semantic_mode_adds_embedding_candidate_facts():
    rows = classify_delivery_lake_rows(
        commit_rows=[{
            "org": "Acme",
            "repo": "backend",
            "sha": "abc123",
            "subject": "simplify daily card oracle resolver",
            "committed_at": _ts("2026-04-02T00:00:00"),
        }],
        semantic_mode="hybrid",
        embedding_client=FakeEmbeddingClient(),
        embedding_threshold=0.7,
        embedding_model="nomic-ai/nomic-embed-text-v1.5",
    )

    embedding_keys = {
        (row["unit_kind"], row["unit_id"], row["category_namespace"], row["category"])
        for row in rows
        if row["source"] == "embedding"
    }

    assert ("commit", "abc123", "work_type", "refactor") in embedding_keys
    assert all(row["classifier_version"] == "embedding-sim-v1" for row in rows if row["source"] == "embedding")
    assert all(row["embedding_model"] == "nomic-ai/nomic-embed-text-v1.5" for row in rows if row["source"] == "embedding")


def test_embed_semantic_units_persists_vector_rows():
    unit = semantic_unit_from_commit_row({
        "org": "Acme",
        "repo": "backend",
        "sha": "abc123",
        "subject": "refactor: simplify service",
        "committed_at": _ts("2026-04-02T00:00:00"),
    })

    rows = embed_semantic_units([unit], FakeEmbeddingClient(), "fake-embed")

    assert len(rows) == 1
    row = rows[0]
    assert row["unit_kind"] == "commit"
    assert row["unit_id"] == "abc123"
    assert row["embedding_model"] == "fake-embed"
    assert row["embedding"] == [1.0, 0.0, 0.0]
    assert row["embedding_dimensions"] == 3
    assert len(row["text_hash"]) == 64


def test_taxonomy_entries_have_embedding_text():
    assert any(entry.namespace == "work_type" and entry.category == "refactor" and "refactor" in entry.text for entry in TAXONOMY_ENTRIES)


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
