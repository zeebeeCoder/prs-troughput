# Traceability Insights

Traceability answers whether delivery-lake units can be connected to an external work anchor such as a ticket or spec.

## Coverage summary

`traceability` remains the compact health summary:

```bash
uv run pr-metrics --org your-org --repo backend-api --insight traceability --days 30
```

It reports aggregate task/spec marker coverage for PR, commit, and branch grains.

## Unit-level gaps

`untraced_units` lists actionable units with no `task_id` and no `spec_name`:

```bash
uv run pr-metrics --org your-org --repo backend-api --insight untraced_units --days 30 --format csv
```

Fields include:

- `unit_kind` and `unit_id`
- `org` / `repo`
- `actor`
- `observed`
- semantic rollups: `work_types`, `branch_roles`, `components`
- `churn`, `changed_files`
- `summary`, `url`, `head_sha`

Rows are ordered by churn and changed-file count so large untraced changes rise to the top.

## Breakdowns

`traceability_breakdown` groups traced vs untraced coverage by:

- week
- org / repo
- unit kind
- actor
- semantic work type or branch role when `semantic_categories` exist

```bash
uv run pr-metrics --org your-org --repo backend-api --insight traceability_breakdown --days 30
```

This is the manager-facing bridge between raw traceability health and attribution questions such as:

- Which authors produce the most untraced work?
- Which repos or weeks have traceability regressions?
- Is untraced work concentrated in feature/refactor/security lanes?
- Is missing traceability acceptable environment/release branch noise or real delivery work?

## Current source of truth

The first implementation reuses existing raw fields and `semantic_categories`:

- `task_id`
- `spec_name`
- semantic `work_type`, `branch_role`, and `component` category facts

A separate `traceability_facts` dataset is deferred until propagation rules become more sophisticated, such as branch-to-commit, PR-to-delivery, or semantic inferred feature names.
