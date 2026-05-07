# Foundational Ledger Grain Contracts

The delivery ledger treats Git as an event/source ledger rather than a default-branch-only commit list.

## Durable grains

### `commits`

Canonical commit facts: one row per observed `(org, repo, sha)` in the latest view.

Sources can include:

- default branch commit scans
- GitHub PR commit-list API rows
- active branch compare scans

Duplicate observations of the same SHA are deduped into one canonical commit fact.

### `commit_links`

Source membership facts: one row per observed commit source.

Important fields:

- `sha`
- `source_kind`: `default_branch`, `pr_commit`, or `branch_commit`
- `source_id`: e.g. `default`, `pr/7`, `branch/feature/foo`
- `pr_number`
- `branch`
- `evidence`

This table preserves where the commit was seen without double-counting canonical commit identity.

### `delivery_events`

Default-branch landing events: one row per delivered default-branch SHA.

`delivery_mode` values:

- `squash` — one-parent default-branch commit with PR evidence
- `merge_commit` — multi-parent default-branch commit
- `direct_main_candidate` — one-parent default-branch commit without PR evidence

## Test contracts

CI tests generate a temporary local Git repository for deterministic topology:

1. feature branch with three commits
2. squash merge to default branch as `feat: squashed feature (#7)`
3. direct default-branch commit with no PR evidence
4. branch with no PR to model invisible WIP

The contract asserts:

- branch commits remain authored commit events after squash
- squash delivery commit is not direct-main
- direct default-branch commit is a `direct_main_candidate`
- branch-only commits are not delivery events
- commit links preserve PR/branch/default source evidence

GitHub PR commit API behavior is covered with mocked payloads so branch-deletion recovery does not require live GitHub credentials in CI.

## Live fixture option

If a persistent live integration target is needed, create a tiny repo such as `zeebeeCoder/pr-metrics-ledger-fixture` with:

1. one direct-main commit
2. one squash-merged PR with 3 commits
3. one merge-commit PR
4. one open PR
5. one no-PR branch ahead of default

This should remain an optional/manual integration check because it depends on `gh auth`, API limits, and mutable GitHub state.
