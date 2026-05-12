# Data Contract — `prs-troughput`

This document describes the **canonical data layer** that outer agents (LLMs, notebooks, BI tools) consume. Schema, partitioning, and the de-duplicated views to prefer over raw parquet globs.

> If you are an agent landing here for analysis, **read this first, then read `analysis-playbook.md`** for the methodology.

## Layout

All data is written under `output/`. Two roots:

| Root | Grain | Notes |
|---|---|---|
| `output/data/` | PRs (one row per PR) | Hive partitioned by `org/year/month` |
| `output/ledger/<grain>/` | commits, branches, etc. | Hive partitioned by `org/year/month` |

Hive partitioning means **all parquet readers should use `union_by_name=true`** to handle schema evolution across collection runs:

```sql
SELECT * FROM read_parquet('output/ledger/commits/**/*.parquet', union_by_name=true)
```

## Canonical `*_latest` views (prefer these)

`src/pr_metrics/insights.py:create_delivery_lake_views()` generates de-duplicated, time-windowed views over the raw parquet. **Always use these for analysis**, not raw `read_parquet` globs (which can expose snapshot duplicates on grains where the primary key isn't part of the snapshot — confirmed for `branches`).

| View | Source grain | Dedup key | When to use |
|---|---|---|---|
| `prs_latest` | `output/data/` | `(org, repo, pr_number)` | All PR analysis |
| `commits_latest` | `output/ledger/commits/` | `sha` | All commit analysis |
| `branches_latest` | `output/ledger/branches/` | `(org, repo, branch)` | Branch / WIP analysis |
| `delivery_events_latest` | `output/ledger/delivery_events/` | `(org, repo, delivery_sha)` | Lead-time / delivery cadence |
| `semantic_categories_latest` | `output/ledger/semantic_categories/` | `(unit_id, category, source)` | Multi-source labels |
| `semantic_embeddings_latest` | `output/ledger/semantic_embeddings/` | `(unit_id, embedding_model)` | Vector search |

These views are bootstrapped via Python — outer agents working in pure SQL should run `views/setup.sql` (which inlines the same dedup logic) before any analysis.

## Grain reference

### `prs_latest` — Pull Requests
One row per PR. Source: GitHub CLI via `gh`.

| Column | Type | Notes |
|---|---|---|
| `org`, `repo` | varchar | partition keys |
| `pr_number` | bigint | per-repo unique |
| `author` | varchar | GitHub login |
| `title`, `body`, `url` | varchar | PR text |
| `head_ref`, `base_ref`, `head_sha` | varchar | branch + sha pointers |
| `created_at`, `updated_at`, `merged_at`, `closed_at` | timestamp tz | lifecycle |
| `first_review_at`, `latest_review_at` | timestamp tz | review timing |
| `state` | varchar | open / closed / merged |
| `is_draft` | boolean | |
| `additions`, `deletions`, `pr_size` | bigint | line metrics |
| `commits` | bigint | commit count in PR |
| `changed_files` | bigint | |
| `reviews`, `reviewers` | bigint, varchar | review activity |
| `review_decision` | varchar | APPROVED / REVIEW_REQUIRED / etc |
| `review_request_count`, `requested_reviewers` | bigint, varchar | |
| `approvals_count`, `changes_requested_count` | bigint | |
| `ci_state`, `checks_failed_count`, `checks_pending_count` | varchar, bigint | CI |
| `mergeable`, `merge_state_status` | varchar | conflict signals |
| `merged_by`, `self_merged` | varchar, boolean | |
| `time_to_merge_hours`, `time_to_first_review_hours` | double | derived |
| `task_id` | varchar | extracted (e.g. `PRD-XXXXX`); often null |
| `spec_name` | varchar | currently always null — parser known broken |
| `labels` | varchar | comma-separated |
| `comments_count` | bigint | non-review comments |
| `collected_at` | timestamp tz | snapshot time |

### `commits_latest` — Git commits
One row per `sha`. Source: GitHub commits API + branch scan.

| Column | Type | Notes |
|---|---|---|
| `org`, `repo` | varchar | partition keys |
| `sha` | varchar | primary key |
| `author_name`, `author_email` | varchar | from git author trailer — **identity collisions present**, see `views/contributors.sql` |
| `committer_name`, `committer_email` | varchar | usually = author |
| `authored_at`, `committed_at` | timestamp tz | author-local TZ preserved |
| `subject`, `body` | varchar | full commit message |
| `conventional_type`, `conventional_scope` | varchar | parsed from subject prefix |
| `activity_class` | varchar | **deterministic v1 classifier** — has known blind spots (`other` bucket). See `analysis-playbook.md` for v2 cascade. |
| `parent_count`, `is_merge_commit`, `is_revert` | bigint, boolean | structural |
| `source_kinds`, `branch_refs` | varchar | comma-separated |
| `on_main`, `is_direct_main` | boolean | direct-to-default-branch flag |
| `pr_number` | double | PR linkage when known |
| `additions`, `deletions`, `changed_files` | double | line metrics |
| `top_level_dirs`, `file_exts` | varchar | comma-separated |
| `task_id`, `spec_name` | varchar | extracted |
| `collected_at` | timestamp tz | |

### `commit_files` — per-file commit facts
One row per (`sha`, `path`). Source: GitHub commit API.

| Column | Type | Notes |
|---|---|---|
| `sha`, `path` | varchar | composite key |
| `status` | varchar | added / modified / removed |
| `additions`, `deletions` | bigint | |
| `top_level_dir`, `extension` | varchar | |
| `is_test`, `is_generated`, `is_sensitive` | boolean | path heuristics |

### `commit_links` — sha → PR/branch linkage
One row per (`sha`, `source_kind`, `source_id`). Reveals where a commit was discovered (default-branch scan, PR commit list, branch ahead-list). **A single sha typically appears 1–3 times here.**

| Column | Type | Notes |
|---|---|---|
| `sha` | varchar | |
| `source_kind` | varchar | `default_branch` / `pr` / `branch` |
| `source_id` | varchar | PR number or branch name |
| `pr_number`, `branch` | double, varchar | |
| `evidence` | varchar | how the link was inferred |

Use this grain to attach branch names to commits — the join is `commits_latest c JOIN commit_links cl ON c.sha = cl.sha WHERE cl.branch IS NOT NULL`.

### `branches_latest` — Remote branch snapshots
One row per (`org`, `repo`, `branch`).

| Column | Type | Notes |
|---|---|---|
| `branch` | varchar | |
| `head_sha` | varchar | join to `commits_latest.sha` |
| `last_commit_at`, `last_author` | timestamp tz, varchar | |
| `ahead_main`, `behind_main` | bigint | vs default branch |
| `has_open_pr` | boolean | |
| `pr_number`, `pr_title`, `pr_url` | double, varchar, varchar | linked PR if any |
| `task_id`, `spec_name` | varchar | extracted from branch name |
| `default_branch`, `default_head_sha` | varchar | for comparison |

### `delivery_events_latest` — Delivery / merge events
One row per (`org`, `repo`, `delivery_sha`). Captures when work landed on the default branch (via PR merge or direct push).

| Column | Type | Notes |
|---|---|---|
| `delivery_sha` | varchar | the merged/delivered commit |
| `delivered_at` | timestamp tz | |
| `delivery_mode` | varchar | `pr_merge` / `direct_push` / etc |
| `pr_number` | double | |
| `evidence` | varchar | |

### `semantic_categories_latest` — Multi-source category labels
One row per (`unit_id`, `category`, `source`). Each unit (commit/PR/branch) can carry many category facts from many sources.

| Column | Type | Notes |
|---|---|---|
| `unit_kind` | varchar | `commit` / `pr` / `branch` |
| `unit_id` | varchar | sha / pr_number / branch name |
| `category_namespace`, `category` | varchar | e.g. namespace=`work_type`, category=`feature` |
| `score`, `confidence` | double, varchar | per-fact strength |
| `source` | varchar | `rule` / `embedding` / `propagated` |
| `evidence` | varchar | what triggered the fact |
| `classifier_version`, `taxonomy_version`, `embedding_model` | varchar | provenance |
| `classified_at`, `observed_at` | timestamp tz | |

Multiple facts per unit is **intentional** — this grain doesn't pick a winner. Picking a single label is the consumer's job (see `analysis-playbook.md` §2).

### `semantic_embeddings_latest` — Persisted unit vectors
One row per (`unit_id`, `embedding_model`).

| Column | Type | Notes |
|---|---|---|
| `unit_kind`, `unit_id` | varchar | |
| `text_hash`, `text` | varchar | what was embedded |
| `embedding` | DOUBLE[] | vector — 768 dims for nomic-embed-text-v1.5 |
| `embedding_dimensions` | bigint | |
| `embedding_model` | varchar | |
| `tokens`, `error` | bigint, varchar | |

Query with DuckDB `list_cosine_similarity(embedding, [...])` for nearest-neighbor search.

## Identity normalization (read this before grouping by author)

Author identity collides across grains:
- Same human appears under multiple `author_name` values: `Zeebee` / `Zeebee Siwiec` / `zeebeeCoder` are one person.
- `author_email` is more stable than `author_name`.
- PR `author` is GitHub login (different namespace from git committer).

**Always run `views/contributors.sql` first** to materialize a `contributors` view that resolves these. Never inline `CASE WHEN lower(author_name) IN (...)` in analysis queries — it drifts and silently miscounts.

## Timezone handling

`authored_at` and `committed_at` carry the **author's local timezone** as recorded by their git config. PR timestamps (`created_at`, etc.) are UTC.

Three modes for time-of-day analysis (state your choice in any output):
- **author-local** — preserves personal work patterns (default; what the punchcard view does)
- **UTC** — canonical for cross-team comparisons
- **fixed TZ** — anchor to leadership working hours; reveals off-hours work *from your perspective*

Use `AT TIME ZONE 'UTC'` or similar to convert.

## Window conventions

`days_back` is the standard window parameter, applied to the relevant timestamp:
- PR analysis: `created_at >= now() - INTERVAL N DAY`
- Commit analysis: `authored_at >= now() - INTERVAL N DAY`
- Branch analysis: `last_commit_at >= now() - INTERVAL N DAY`

When unsure, **use 90 days** — matches what the eval contract uses.

## What's NOT in this data layer

- Per-file blame / line ownership (would require git history walk)
- Code review *content* (review bodies are not collected — only counts and decisions)
- Slack / Linear / Jira context (linked via `task_id` only — those systems are external)
- Per-commit author timezone offset as a separate column (parse it from `authored_at` if needed)

## Schema evolution

Hive partitioning + `union_by_name=true` lets new columns appear in newer parquet files without breaking old readers. **Existing columns never change type silently** — if a type changes, the partition path also changes (e.g. through a schema version segment). Check `output/ledger/<grain>/` partition listings if a query suddenly returns nulls.
