# Storage Layout

`pr-metrics` owns two local storage roots by default:

| Purpose | Default | Override |
|---|---|---|
| Data lake | `${XDG_DATA_HOME:-~/.local/share}/pr-metrics/lake` | `--output-dir` / `PR_METRICS_OUTPUT_DIR` |
| Clone cache | `${XDG_CACHE_HOME:-~/.cache}/pr-metrics/clones/<org>/<repo>` | `--cache-dir` / `PR_METRICS_CACHE_DIR` |

The data lake contains regenerated parquet/CSV artifacts and collection telemetry. The clone cache contains tool-managed git clones used for ledger collection.

## Telemetry layout

Collection runs write JSONL phase telemetry by default:

```text
<lake>/telemetry/runs/<run_id>.jsonl
```

Each event includes `run_id`, timestamp, `phase`, `elapsed_ms`, `status`, and any phase-specific fields such as `org`, `repo`, `rows`, `clone_path`, or `default_ref`. Use `--no-telemetry` to opt out for a run.

## Hybrid clone lifecycle

- First encounter: `git clone --no-checkout` into the clone cache. Hybrid extraction intentionally uses full clones because `git log --numstat` against blobless partial clones can trigger slow on-demand promisor fetches.
- Later runs: `git fetch --prune origin` before extraction.
- One `CloneCache` instance remembers clones fetched in the current process to avoid double-fetching when commits and branches are collected together.
- Cache mutations and extraction are protected by a per-clone lock.
- Access time is tracked with `.pr-metrics.access` for explicit pruning.

## Cache management

```bash
uv run pr-metrics cache list
uv run pr-metrics cache du
uv run pr-metrics cache prune --older-than 30d          # preview by default
uv run pr-metrics cache prune --older-than 30d --yes    # delete matches
uv run pr-metrics cache clear --org my-org
```

No cache command requires GitHub authentication or an `--org` collection target.

## Read-only extraction boundary

`src/pr_metrics/local_git.py` only runs read-only commands (`rev-parse`, `symbolic-ref`, `log`, `for-each-ref`, `rev-list`). Clone/fetch operations are isolated in `src/pr_metrics/clone_cache.py` and only operate under the cache root.
