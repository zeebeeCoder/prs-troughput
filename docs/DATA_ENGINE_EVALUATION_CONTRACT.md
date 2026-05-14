# Git Delivery Data Engine Evaluation Contract

This contract fixes a small, repeatable repo set for validating the data-engine slices before expanding to org-wide reporting.

## Selection method

Use the `active_repos` insight against recent PR parquet to rank candidates by PR intensity, authors, churn, and recency:

```bash
uv run pr-metrics --org Eve-World-Platform --insight active_repos --days 120
uv run pr-metrics --org NFHotelAI --insight active_repos --days 120
```

## Contract repos

| Org | Repo | Why included |
|-----|------|--------------|
| `Eve-World-Platform` | `coto-joy` | Highest current Eveworld PR intensity in local data; already exercises large churn, direct-main commits, branch WIP, and semantic activity mix. |
| `NFHotelAI` | `nfhotel_backend` | Tied top NFHotel PR intensity; backend lane gives moderate churn and review/branch cleanup signals. |
| `NFHotelAI` | `nfhotel_frontend` | Tied top NFHotel PR intensity; frontend lane gives high churn and direct-main/large-change stress cases. |
| `NFHotelAI` | `nf_next` | Explicit acceptance target from T0016; must surface `DEV-3871/print-form` invisible WIP and recent direct-to-main work. |

## Refresh commands

Use the default full delivery collection; tune concurrency only if the local machine or network needs a lower ceiling:

```bash
uv run pr-metrics --org Eve-World-Platform \
  --repo coto-joy \
  --days 30

uv run pr-metrics --org NFHotelAI \
  --repo nfhotel_backend,nfhotel_frontend,nf_next \
  --days 30
```

## Required insight slices

Each contract run should produce non-error output for:

```bash
uv run pr-metrics --org Eve-World-Platform --repo coto-joy --insight kinetics_weekly --days 30
uv run pr-metrics --org Eve-World-Platform --repo coto-joy --insight direct_main_risk --days 30
uv run pr-metrics --org Eve-World-Platform --repo coto-joy --insight traceability --days 30

uv run pr-metrics --org NFHotelAI --repo nfhotel_backend,nfhotel_frontend,nf_next --insight kinetics_weekly --days 30
uv run pr-metrics --org NFHotelAI --repo nfhotel_backend,nfhotel_frontend,nf_next --insight invisible_wip --days 30
uv run pr-metrics --org NFHotelAI --repo nfhotel_backend,nfhotel_frontend,nf_next --insight traceability --days 30
```

## Acceptance signals

The data engine is useful when these slices support both data models:

1. **Intensity** — aggregateable heatmap facts by time bucket, repo, actor, lane, work type, and churn.
   - `intensity_weekly`
   - `activity_mix`
   - `review_queue`
2. **Vector / kinetics** — directional change across buckets or snapshots.
   - `kinetics_weekly`
   - `invisible_wip`
   - direct-main percentage and churn deltas

Concrete contract checks:

- `active_repos` ranks the contract repos as active/recent.
- `kinetics_weekly` shows weekly PR/commit velocity plus deltas.
- `direct_main_risk` ranks direct-main commits by risk score.
- `invisible_wip` surfaces `NFHotelAI/nf_next` branch `DEV-3871/print-form`.
- `traceability` reports task/spec coverage for PR, commit, and branch grains.
- Parquet schemas keep nullable text fields as `VARCHAR`, especially `spec_name`, `task_id`, and `ci_state`.
- `--validate-local` compares commit and branch facts against a local clone without mutating that clone.

## Current sampled results, 2026-05-01

- NFHotel contract refresh collected 51 PR rows, 120 commit rows, 878 commit-file rows, and 115 branch rows.
- `invisible_wip` surfaced `NFHotelAI/nf_next` branch `DEV-3871/print-form`, 14 commits ahead, last touched 2026-04-30.
- NFHotel traceability over the contract repos: PRs 61.2% with task IDs, commits 51.7%, branches 20.9%.
- `coto-joy` traceability: PRs 40.0% with task IDs, commits 16.0%, branches 22.2%.
- Local validation against `/Users/zbigniewsiwiec/code/coto/coto-joy` found 39/39 comparable commit rows exact; one newest default-branch commit was missing locally because the local remote-tracking ref was stale. Branch rows were marked not comparable for the same missing `default_head_sha`, proving the validator does not mutate/fetch the local repo.
