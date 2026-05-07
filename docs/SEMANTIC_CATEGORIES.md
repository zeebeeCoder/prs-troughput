# Semantic Category Facts

Semantic categories are deterministic, multi-label facts over delivery-lake units. They are designed as a durable attribution layer rather than a single denormalized `category` column.

## Dataset

Rows are written to:

```text
output/ledger/semantic_categories/
```

Durable grain:

```text
(org, repo, unit_kind, unit_id, category_namespace, category, classifier_version, taxonomy_version)
```

Core columns:

- `unit_kind` — `pr`, `commit`, or `branch`
- `unit_id` — PR number, commit SHA, or branch name
- `category_namespace` — e.g. `work_type`, `branch_role`, `traceability`, `quality`, `component`
- `category` — namespace-specific label
- `score` / `confidence` — deterministic confidence signal
- `source` — currently `rule` or `propagated`
- `evidence` — short explainable reason
- `classifier_version` — currently `deterministic-rules-v1`
- `taxonomy_version` — currently `semantic-taxonomy-v1`
- `embedding_model` — currently `none`; reserved for a later embedding pass

## Taxonomy v1

Initial namespaces:

- `work_type`: `feature`, `bug_fix`, `refactor`, `docs`, `test`, `chore`, `infra`, `security_auth`, `performance`, `dependency`, `agent_tooling`
- `branch_role`: `feature_wip`, `ticket_wip`, `environment`, `deployment`, `release`, `hotfix`, `bot_generated`
- `traceability`: `ticket_linked`, `spec_linked`, `untraced`
- `quality`: `refactoring`, `test_coverage`, `generated_code`, `sensitive_path`
- `component`: `backend`, `frontend`, `data`, `infra`, `auth`, `oracle`, `payments`, `onboarding`
- `ticket` and `spec`: propagated concrete identifiers for grouping

A unit can receive multiple labels. Example:

```text
commit abc123:
  work_type=refactor
  quality=refactoring
  quality=sensitive_path
  traceability=ticket_linked
  ticket=DEV-123
  component=auth
```

## Current classifier

The first implementation is deterministic only:

- Conventional Commit type maps to `work_type`.
- Existing `activity_class` is used as a fallback work-type signal.
- `task_id` and `spec_name` become traceability facts and propagated concrete `ticket`/`spec` facts.
- Branch names classify obvious environment, deployment, release, hotfix, bot, ticket-WIP, and feature-WIP roles.
- Path/text cues classify test coverage, generated code, sensitive paths, agent tooling, and coarse components.

Embeddings and LLM review are intentionally deferred until this persisted fact grain is stable.

## Insights

- `invisible_wip` uses `branch_role` facts to exclude environment/deployment/release/bot branches when semantic categories exist.
- `refactoring_activity` reports refactor-attributed commits, PRs, and branches by week, repo, actor, unit kind, churn, and traceability coverage.
