# Testing

Default tests are offline and should complete quickly:

```bash
uv run pytest
```

Guardrails:

- `tests/conftest.py` fails any accidental real `gh` subprocess invocation.
- Git plumbing tests use real `git` against temporary repositories and `file://` bare remotes.
- No test requires GitHub credentials or network access.
- XDG and `PR_METRICS_*` path tests monkeypatch environment variables and only write under `tmp_path`.

Hybrid ledger coverage includes:

- `CloneCache` first clone, subsequent fetch, no double-fetch in one run, disk usage, clear, prune, and lock contention.
- `local_git` first-parent commit extraction with `--numstat`, commit-file facts, PR number parsing from `(#NNN)`, freshness checks, and open-PR branch ahead/behind counts.
- CLI routing from `--ledger-source hybrid` into local-git extraction without changing the default `github` ledger path.

Benchmarking the real 18-repo Eve-World workload remains manual/opt-in because it requires network and local cache state. Record wall time against the 848.8s GitHub-heavy baseline when running it.
