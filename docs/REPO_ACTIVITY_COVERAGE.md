# Repository Activity and Lake Coverage

`active_repos` is a local delivery-lake insight. It ranks repositories by facts already collected into parquet; it does not call GitHub live during insight execution.

## Why this matters

A repo can be active without recent PR rows:

- commits may land directly on the default branch
- branch WIP may exist before PR creation
- PRs may be stale or outside the selected window
- local parquet may only contain a subset of org repositories

The previous `active_repos` query looked only at `prs_latest`, which made it easy to under-report active repositories for orgs such as EveWorldPlatform.

## `active_repos`

```bash
uv run pr-metrics --org your-org --insight active_repos --days 90
```

The insight now unions local activity from:

- `prs_latest`
- `commits_latest`
- `delivery_events_latest`
- `branches_latest`

Output includes:

- `pr_events`
- `commit_events`
- `delivery_events`
- `active_branches`
- `activity_churn`
- `latest_activity`
- `activity_sources`
- `local_lake_status`

`local_lake_status` distinguishes PR-only local evidence from multi-source delivery-lake evidence.

## `repo_lake_coverage`

```bash
uv run pr-metrics --org your-org --insight repo_lake_coverage --days 90
```

This is the companion diagnostic. It shows whether each repo has local parquet coverage for:

- PR rows
- commit rows
- branch rows
- delivery rows
- semantic category rows

Use this before manager-facing analysis to avoid mistaking a local-lake coverage gap for real org inactivity.

## What this does not do yet

These insights do not perform live GitHub org inventory. A future slice can add a separate `repo_inventory` dataset or `--discover-repos` command that writes live GitHub repo metadata (`pushed_at`, archived/fork/private flags, default branch) and compares that inventory against local lake coverage.
