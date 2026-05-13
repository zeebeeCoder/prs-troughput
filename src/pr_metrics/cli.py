#!/usr/bin/env python3
"""CLI entry point for PR metrics tool."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from .embeddings import DEFAULT_FIREWORKS_DIMENSIONS, DEFAULT_FIREWORKS_MODEL, create_fireworks_embedding_client
from .clone_cache import CloneCache
from .github import (
    ensure_gh_authenticated,
    get_active_repos_from_search,
    get_gh_call_count,
    get_open_pr_branch_map,
    get_org_repos,
    get_repo_branch_commits,
    get_repo_branches,
    get_repo_commits,
    get_repo_pr_commits,
    get_repo_prs,
    reset_gh_call_count,
)
from .insights import INSIGHTS, create_delivery_lake_views, render_dataframe, run_insight
from . import local_git
from .paths import resolve_cache_dir, resolve_data_lake_dir
from .processor import (
    load_latest_data,
    process_branches_to_rows,
    process_commit_ledger_to_rows,
    process_prs_to_dataframe,
)
from .reports import (
    generate_contributor_report,
    generate_delivery_report,
    generate_markdown_report,
    generate_rich_terminal_report,
)
from .semantic import classify_delivery_lake_rows, embed_semantic_units, semantic_units_from_delivery_lake_rows
from .storage import write_rows_to_hive, write_to_hive
from .utils import resolve_org, sanitize_org_name
from .validation import validate_local_repo


OUTPUT_DIR = str(resolve_data_lake_dir())


def _select_repos(args, org):
    """Resolve repository list for a collection run."""
    if args.repo:
        repo_names = [repo.strip() for repo in args.repo.split(',') if repo.strip()]
        return [{'name': repo_name} for repo_name in repo_names]

    if args.full_scan:
        repos = get_org_repos(org)
        print(f"📁 Processing {len(repos)} repositories (full scan)")
        return repos

    return get_active_repos_from_search(org, args.days)


def _fetch_pr_data(args, org, repos):
    """Fetch raw PR data for each selected repository."""
    all_prs_data = {}
    for i, repo in enumerate(repos, 1):
        repo_name = repo['name']
        print(f"  {i}/{len(repos)} PRs: {repo_name}")
        prs = get_repo_prs(org, repo_name, args.days)
        if prs:
            all_prs_data[repo_name] = prs
    return all_prs_data


def _filter_active_pr_rows(df, args):
    """Apply minimum-PR repo filtering unless the user scoped repositories explicitly."""
    if args.repo:
        return df

    repo_counts = df['repo'].value_counts()
    active_repos = repo_counts[repo_counts >= args.min_prs].index.tolist()
    if not active_repos:
        print(f"⚠️  No repos found with at least {args.min_prs} PRs")
        return pd.DataFrame()

    filtered_count = len(repo_counts) - len(active_repos)
    if filtered_count > 0:
        print(f"📊 Filtered out {filtered_count} repos with fewer than {args.min_prs} PRs")
    return df[df['repo'].isin(active_repos)]


def _print_pr_collection_results(df, days):
    """Print collection summary metrics."""
    total_prs = len(df)
    merged_df = df[df['state'] == 'merged']
    merged_prs = len(merged_df)
    merge_rate = (merged_prs / total_prs * 100) if total_prs > 0 else 0

    print("\n🎯 PR RESULTS:")
    print(f"   Total PRs: {total_prs}")
    print(f"   Merged: {merged_prs} ({merge_rate:.1f}%)")
    print(f"   Daily throughput: {merged_prs / days:.1f} PRs/day")
    print(f"   Avg PR size: {df['pr_size'].mean():.0f} lines")
    if not merged_df.empty:
        print(f"   Avg time to merge: {merged_df['time_to_merge_hours'].mean():.1f} hours")
    print(f"   Top authors: {dict(df['author'].value_counts().head(5))}")


def _persist_pr_rows(df, pr_rows, org):
    """Persist PR rows to Hive partitions plus legacy CSV backup."""
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    Path(f"{OUTPUT_DIR}/data").mkdir(parents=True, exist_ok=True)

    sanitized_org = sanitize_org_name(org)
    write_to_hive(pr_rows, sanitized_org, base_dir=f"{OUTPUT_DIR}/data")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_file = f"{OUTPUT_DIR}/pr_data_{sanitized_org}_{timestamp}.csv"
    df.to_csv(csv_file, index=False)

    print(f"\n💾 PR data saved to Hive partitions: {OUTPUT_DIR}/data/")
    print(f"   Legacy CSV backup: {csv_file}")


def _collect_prs(args, org, repos):
    """Collect and persist PR rows, preserving legacy behavior."""
    pr_rows = process_prs_to_dataframe(_fetch_pr_data(args, org, repos), org)
    if not pr_rows:
        print("No PR data found")
        return []

    df = _filter_active_pr_rows(pd.DataFrame(pr_rows), args)
    if df.empty:
        return []

    pr_rows = df.to_dict('records')
    _print_pr_collection_results(df, args.days)
    _persist_pr_rows(df, pr_rows, org)
    return pr_rows


def _clone_cache_from_args(args):
    """Return a per-invocation CloneCache so commits/branches do not double-fetch."""
    cache = getattr(args, "_clone_cache", None)
    if cache is None:
        cache = CloneCache(resolve_cache_dir(getattr(args, "cache_dir", None)))
        setattr(args, "_clone_cache", cache)
    return cache


def _max_workers(args, repos):
    """Resolve bounded repo-level concurrency."""
    configured = getattr(args, "max_concurrency", None)
    if configured:
        return max(1, configured)
    return max(1, min(8, len(repos)))


def _collect_commit_ledger_github(args, org, repos):
    """Collect commit ledger rows via the legacy GitHub API path."""
    all_commits_data = {}
    for i, repo in enumerate(repos, 1):
        repo_name = repo['name']
        print(f"  {i}/{len(repos)} commits: {repo_name}")
        include_files = not args.skip_commit_files
        commits = []
        commits.extend(get_repo_commits(
            org,
            repo_name,
            days_back=args.days,
            limit=args.commit_limit,
            include_files=include_files,
        ))
        commits.extend(get_repo_pr_commits(
            org,
            repo_name,
            days_back=args.days,
            pr_limit=getattr(args, 'pr_limit', 100),
            commit_limit=getattr(args, 'pr_commit_limit', 100),
            include_files=include_files,
        ))
        commits.extend(get_repo_branch_commits(
            org,
            repo_name,
            branch_limit=args.branch_limit,
            commit_limit=getattr(args, 'branch_commit_limit', 100),
            include_files=include_files,
        ))
        if commits:
            all_commits_data[repo_name] = commits
    return all_commits_data


def _extract_local_commits_for_repo(args, org, repo_name, cache, stats):
    """Ensure a cached clone and extract local commit facts for one repo."""
    clone = cache.ensure_clone(org, repo_name)
    local_git.ensure_fresh_refs(
        clone,
        args.days,
        allow_stale=getattr(args, "allow_stale", False),
        stats=stats,
    )
    return repo_name, local_git.extract_commits(
        clone,
        days_back=args.days,
        full_body=getattr(args, "full_body", False),
        stats=stats,
    )


def _collect_commit_ledger_hybrid(args, org, repos):
    """Collect commit ledger rows from cache-owned local git clones."""
    cache = _clone_cache_from_args(args)
    stats = getattr(args, "_git_stats", None) or local_git.GitCommandStats()
    setattr(args, "_git_stats", stats)
    print(f"🧊 Using clone cache: {cache.cache_root}")
    all_commits_data = {}
    with ThreadPoolExecutor(max_workers=_max_workers(args, repos)) as executor:
        futures = {
            executor.submit(_extract_local_commits_for_repo, args, org, repo['name'], cache, stats): repo['name']
            for repo in repos
        }
        for index, future in enumerate(as_completed(futures), 1):
            repo_name = futures[future]
            print(f"  {index}/{len(repos)} local commits: {repo_name}")
            name, commits = future.result()
            if commits:
                all_commits_data[name] = commits
    return all_commits_data


def _collect_commit_ledger(args, org, repos):
    """Collect and persist commit ledger rows across configured sources."""
    if getattr(args, "ledger_source", "github") == "hybrid":
        all_commits_data = _collect_commit_ledger_hybrid(args, org, repos)
    else:
        all_commits_data = _collect_commit_ledger_github(args, org, repos)

    commit_rows, file_rows, link_rows, delivery_rows = process_commit_ledger_to_rows(all_commits_data, org)
    write_rows_to_hive(commit_rows, f"{OUTPUT_DIR}/ledger/commits", table_name="commits")
    write_rows_to_hive(link_rows, f"{OUTPUT_DIR}/ledger/commit_links", table_name="commit_links")
    write_rows_to_hive(delivery_rows, f"{OUTPUT_DIR}/ledger/delivery_events", table_name="delivery_events")
    if not args.skip_commit_files:
        write_rows_to_hive(file_rows, f"{OUTPUT_DIR}/ledger/commit_files", table_name="commit_files")


def _extract_local_branches_for_repo(args, org, repo_name, cache, stats):
    """Ensure a cached clone and extract open-PR branch facts for one repo."""
    clone = cache.ensure_clone(org, repo_name)
    open_prs = get_open_pr_branch_map(org, repo_name, limit=getattr(args, "pr_limit", 100))
    local_git.ensure_fresh_refs(
        clone,
        args.days,
        allow_stale=getattr(args, "allow_stale", False),
        stats=stats,
    )
    return repo_name, local_git.extract_branches(clone, open_pr_branch_map=open_prs, stats=stats)


def _collect_branch_ledger_hybrid(args, org, repos):
    """Collect branch rows from local refs, enriched by open PR metadata."""
    cache = _clone_cache_from_args(args)
    stats = getattr(args, "_git_stats", None) or local_git.GitCommandStats()
    setattr(args, "_git_stats", stats)
    all_branch_data = {}
    with ThreadPoolExecutor(max_workers=_max_workers(args, repos)) as executor:
        futures = {
            executor.submit(_extract_local_branches_for_repo, args, org, repo['name'], cache, stats): repo['name']
            for repo in repos
        }
        for index, future in enumerate(as_completed(futures), 1):
            repo_name = futures[future]
            print(f"  {index}/{len(repos)} local branches: {repo_name}")
            name, branches = future.result()
            if branches:
                all_branch_data[name] = branches
    return all_branch_data


def _collect_branch_ledger(args, org, repos):
    """Collect and persist remote branch snapshot rows."""
    if getattr(args, "ledger_source", "github") == "hybrid":
        all_branch_data = _collect_branch_ledger_hybrid(args, org, repos)
    else:
        all_branch_data = {}
        for i, repo in enumerate(repos, 1):
            repo_name = repo['name']
            print(f"  {i}/{len(repos)} branches: {repo_name}")
            branches = get_repo_branches(org, repo_name, limit=args.branch_limit)
            if branches:
                all_branch_data[repo_name] = branches

    branch_rows = process_branches_to_rows(all_branch_data, org)
    write_rows_to_hive(branch_rows, f"{OUTPUT_DIR}/ledger/branches", table_name="branches")


def _view_records(con, available, view_name):
    """Return latest-view records when a delivery-lake view is available."""
    if view_name not in available:
        return []
    return con.execute(f"SELECT * FROM {view_name}").fetchdf().to_dict("records")


def _embedding_client_from_args(args):
    """Create optional embedding client for hybrid semantic mode."""
    if args.semantic_mode != "hybrid":
        return None
    if args.embedding_provider != "fireworks":
        raise ValueError(f"Unsupported embedding provider: {args.embedding_provider}")
    client = create_fireworks_embedding_client(
        config_path=args.embedding_config,
        model=args.embedding_model,
        dimensions=args.embedding_dimensions,
        batch_size=args.embedding_batch_size,
    )
    if client is None:
        print("⚠️  No Fireworks API key found; semantic hybrid mode will persist rule-based facts only")
    return client


def _classify_semantics(args, org):
    """Classify available PR, commit, and branch rows into semantic category facts."""
    con, available = create_delivery_lake_views(
        output_dir=OUTPUT_DIR,
        org=org,
        repo=args.repo,
        days_back=args.days,
    )
    try:
        pr_rows = _view_records(con, available, "prs_latest")
        commit_rows = _view_records(con, available, "commits_latest")
        branch_rows = _view_records(con, available, "branches_latest")
        embedding_client = _embedding_client_from_args(args)
        embedding_model = args.embedding_model if args.semantic_mode == "hybrid" else "none"
        rows = classify_delivery_lake_rows(
            pr_rows=pr_rows,
            commit_rows=commit_rows,
            branch_rows=branch_rows,
            semantic_mode=args.semantic_mode,
            embedding_client=embedding_client,
            embedding_threshold=args.embedding_threshold,
            embedding_model=embedding_model,
        )
        embedding_rows = []
        if args.semantic_mode == "hybrid" and embedding_client is not None:
            units = semantic_units_from_delivery_lake_rows(pr_rows=pr_rows, commit_rows=commit_rows, branch_rows=branch_rows)
            embedding_rows = embed_semantic_units(units, embedding_client=embedding_client, embedding_model=embedding_model)
    finally:
        con.close()

    source_counts = pd.Series([row.get("source") for row in rows]).value_counts().to_dict() if rows else {}
    print(f"✓ Prepared {len(rows)} semantic category rows by source: {source_counts}")
    if args.semantic_mode == "hybrid" and source_counts.get("embedding", 0) == 0:
        print("⚠️  Hybrid semantic mode produced no embedding category facts; check Fireworks key/model access or lower --embedding-threshold")
    write_rows_to_hive(rows, f"{OUTPUT_DIR}/ledger/semantic_categories", table_name="semantic_categories")
    if embedding_rows:
        embedded_count = sum(1 for row in embedding_rows if row.get("embedding") is not None)
        print(f"✓ Prepared {len(embedding_rows)} semantic embedding rows ({embedded_count} with vectors)")
        write_rows_to_hive(embedding_rows, f"{OUTPUT_DIR}/ledger/semantic_embeddings", table_name="semantic_embeddings")


def _collect_ledger(args, org, repos):
    """Collect optional Git delivery ledger datasets."""
    include_commits = args.include_ledger or args.include_commits
    include_branches = args.include_ledger or args.include_branches
    include_semantics = args.classify_semantics

    if not (include_commits or include_branches or include_semantics):
        return

    started = time.monotonic()
    reset_gh_call_count()
    Path(f"{OUTPUT_DIR}/ledger").mkdir(parents=True, exist_ok=True)
    if include_commits:
        _collect_commit_ledger(args, org, repos)
    if include_branches:
        _collect_branch_ledger(args, org, repos)
    if include_semantics:
        _classify_semantics(args, org)
    _print_extraction_summary(args, started)


def _print_extraction_summary(args, started):
    """Print a compact extraction summary for ledger runs."""
    elapsed = time.monotonic() - started
    cache = getattr(args, "_clone_cache", None)
    stats = getattr(args, "_git_stats", None)
    cloned = cache.cloned_count if cache else 0
    fetched = cache.fetched_count if cache else 0
    git_commands = stats.commands if stats else 0
    print(
        "📊 Extraction summary: "
        f"elapsed={elapsed:.1f}s gh_calls={get_gh_call_count()} "
        f"local_git_commands={git_commands} cloned={cloned} fetched={fetched}"
    )



def _build_parser():
    """Create the CLI argument parser."""
    parser = argparse.ArgumentParser(description='Collect PR metrics and Git delivery ledger data using gh + DuckDB')
    parser.add_argument('--days', type=int, default=14, help='Days back to analyze')
    parser.add_argument('--min-prs', type=int, default=3, help='Minimum PRs required to include repo in report (default: 3)')
    parser.add_argument('--full-scan', action='store_true', help='Process all repos instead of just active ones (slower, may hit rate limits)')
    parser.add_argument('--report', action='store_true', help='Generate report from existing data')
    parser.add_argument('--delivery-report', action='store_true', help='Generate combined PR + commit + branch delivery ledger report')
    parser.add_argument('--terminal', action='store_true', help='Generate terminal-friendly report with rich styling')
    parser.add_argument('--org', type=str, help='GitHub organization to analyze (overrides default)')
    parser.add_argument('--repo', type=str, help='Filter by repository name; collection accepts comma-separated names')
    parser.add_argument('--output-dir', default=None,
                        help='Directory for the local parquet data lake and CSV backups (default: PR_METRICS_OUTPUT_DIR or XDG data home)')
    parser.add_argument('--top-n', type=int, default=5, help='Number of top contributors to show individual weekly breakdowns (default: 5)')
    parser.add_argument('--include-ledger', action='store_true', help='Collect commits and branches in addition to PRs')
    parser.add_argument('--ledger-source', choices=('github', 'hybrid'), default='github', help='Ledger data source: github API path or hybrid GitHub signals + local git facts (default: github)')
    parser.add_argument('--cache-dir', default=None, help='Clone cache root for --ledger-source hybrid (default: PR_METRICS_CACHE_DIR or XDG cache home)')
    parser.add_argument('--max-concurrency', type=int, default=None, help='Maximum concurrent repo extractions for hybrid mode (default: min(8, repo_count))')
    parser.add_argument('--full-body', action='store_true', help='Preserve full commit bodies in hybrid mode (default truncates to 8 KiB)')
    parser.add_argument('--allow-stale', action='store_true', help='Allow hybrid extraction when remote refs are older than the --days window')
    parser.add_argument('--include-commits', action='store_true', help='Collect commit event ledger data from default branch, PR commit lists, and branch scans')
    parser.add_argument('--include-branches', action='store_true', help='Collect remote branch snapshot data')
    parser.add_argument('--commit-limit', type=int, default=100, help='Max default-branch commits to collect per repo (default: 100)')
    parser.add_argument('--pr-limit', type=int, default=100, help='Max recent PRs whose commit lists are collected per repo (default: 100)')
    parser.add_argument('--pr-commit-limit', type=int, default=100, help='Max commits to collect per PR via the PR commits API (default: 100)')
    parser.add_argument('--branch-limit', type=int, default=100, help='Max branches to collect per repo (default: 100)')
    parser.add_argument('--branch-commit-limit', type=int, default=100, help='Max ahead commits to collect per branch (default: 100)')
    parser.add_argument('--branch-active-days', type=int, default=30, help='Treat branches with commits in this many days as active WIP (default: 30)')
    parser.add_argument('--skip-commit-files', action='store_true', help='Skip per-file commit facts to reduce GitHub API work')
    parser.add_argument('--classify-semantics', action='store_true', help='Persist semantic category facts for collected PR/commit/branch rows')
    parser.add_argument('--semantic-mode', choices=('rules', 'hybrid'), default='rules', help='Semantic classifier mode: rules only or rules plus embedding candidates (default: rules)')
    parser.add_argument('--embedding-provider', choices=('fireworks',), default='fireworks', help='Embedding provider for semantic hybrid mode (default: fireworks)')
    parser.add_argument('--embedding-model', default=DEFAULT_FIREWORKS_MODEL, help=f'Embedding model for semantic hybrid mode (default: {DEFAULT_FIREWORKS_MODEL})')
    parser.add_argument('--embedding-dimensions', type=int, default=DEFAULT_FIREWORKS_DIMENSIONS, help=f'Embedding dimensions for semantic hybrid mode (default: {DEFAULT_FIREWORKS_DIMENSIONS})')
    parser.add_argument('--embedding-threshold', type=float, default=0.55, help='Cosine threshold for embedding semantic candidates (default: 0.55)')
    parser.add_argument('--embedding-batch-size', type=int, default=32, help='Embedding API batch size for semantic hybrid mode (default: 32)')
    parser.add_argument('--embedding-config', default=None, help='Optional semantic-cli config path containing fireworks_api_key')
    parser.add_argument('--list-insights', action='store_true', help='List reusable DuckDB insight slices')
    parser.add_argument('--insight', type=str, help='Run a named insight slice from existing parquet data')
    parser.add_argument('--print-skill', action='store_true',
                        help='Print the delivery-insights SKILL.md to stdout (pipe to ~/.claude/skills/delivery-insights/SKILL.md to install)')
    parser.add_argument('--print-skill-bundle', action='store_true',
                        help='Print a self-extracting bash script that installs SKILL.md + INSTALL.md + VALIDATION.md + docs/ + views/ + scripts/ to a target dir (pipe to bash)')
    parser.add_argument('--format', choices=('table', 'json', 'csv'), default='table', help='Output format for --insight (default: table)')
    parser.add_argument('--validate-local', type=str, help='Read-only local Git repo path to compare against existing parquet data')
    parser.add_argument('--remote', type=str, default='origin', help='Remote name for --validate-local branch checks (default: origin)')
    return parser


def _handle_list_insights():
    """Print registered insight slices."""
    for name, insight in sorted(INSIGHTS.items()):
        print(f"{name}\t{insight.description}")


def _repo_root() -> Path:
    """Resolve the repo root from this file's location (works regardless of cwd)."""
    return Path(__file__).resolve().parents[2]


def _handle_print_skill():
    """Print the delivery-insights SKILL.md to stdout."""
    skill_path = _repo_root() / "skills" / "delivery-insights" / "SKILL.md"
    if not skill_path.is_file():
        raise FileNotFoundError(
            f"SKILL.md not found at {skill_path}. "
            "Run from a checkout of prs-troughput; the skill assets do not ship with the wheel."
        )
    print(skill_path.read_text(), end="")


def _handle_print_skill_bundle():
    """Emit a self-extracting bash script that recreates the full skill bundle.

    Usage:
        uv run pr-metrics --print-skill-bundle | bash -s ~/.claude/skills/delivery-insights
    The script writes:
      <target>/SKILL.md, INSTALL.md, VALIDATION.md
      <target>/docs/data-contract.md, docs/analysis-playbook.md
      <target>/views/*.sql
      <target>/scripts/*.py and scripts/README.md
    """
    root = _repo_root()
    bundle_files: list[tuple[str, Path]] = []

    skill_dir = root / "skills" / "delivery-insights"
    for name in ("SKILL.md", "INSTALL.md", "VALIDATION.md"):
        path = skill_dir / name
        if path.is_file():
            bundle_files.append((name, path))

    for name in ("data-contract.md", "analysis-playbook.md"):
        path = root / "docs" / name
        if path.is_file():
            bundle_files.append((f"docs/{name}", path))

    views_dir = root / "views"
    if views_dir.is_dir():
        for sql_path in sorted(views_dir.iterdir()):
            if sql_path.suffix in (".sql", ".md"):
                bundle_files.append((f"views/{sql_path.name}", sql_path))

    scripts_dir = skill_dir / "scripts"
    if scripts_dir.is_dir():
        for script_path in sorted(scripts_dir.iterdir()):
            if script_path.suffix in (".py", ".md"):
                bundle_files.append((f"scripts/{script_path.name}", script_path))

    if not bundle_files:
        raise FileNotFoundError(
            f"No skill assets found under {root}. Run from a checkout of prs-troughput."
        )

    print("#!/usr/bin/env bash")
    print("# delivery-insights skill bundle — self-extracting installer")
    print("# Usage: bash this-script <target-dir>   (default: ~/.claude/skills/delivery-insights)")
    print("set -euo pipefail")
    print('TARGET="${1:-$HOME/.claude/skills/delivery-insights}"')
    print('mkdir -p "$TARGET/docs" "$TARGET/views" "$TARGET/scripts"')
    print('echo "Installing delivery-insights to $TARGET …"')
    print()
    # Use a unique, deterministic heredoc terminator to avoid collisions with file content.
    marker_seed = "\n".join(name for name, _ in bundle_files).encode()
    marker = f"DELIVERY_INSIGHTS_EOF_{hashlib.sha256(marker_seed).hexdigest()[:12].upper()}"
    for rel_name, path in bundle_files:
        text = path.read_text()
        # Defensive: warn if the marker happens to appear in content.
        if marker in text:
            raise RuntimeError(f"Heredoc marker {marker} collides with content of {rel_name}; bump the marker logic")
        print(f'cat > "$TARGET/{rel_name}" <<\'{marker}\'')
        # Heredoc body — keep verbatim, no quoting needed because of single-quoted marker.
        print(text, end="" if text.endswith("\n") else "\n")
        print(marker)
        print()
    print('echo "Installed ' + str(len(bundle_files)) + ' files to $TARGET"')
    print('echo "Skill is now active. Test by asking Claude to use the delivery-insights skill."')


def _handle_insight(args, org):
    """Run a named reusable insight slice."""
    df = run_insight(
        args.insight,
        output_dir=OUTPUT_DIR,
        org=org,
        repo=args.repo,
        days_back=args.days,
    )
    print(render_dataframe(df, args.format))


def _handle_validate_local(args, org):
    """Compare collected ledger data with a local clone."""
    if not args.repo or ',' in args.repo:
        raise ValueError("--validate-local requires exactly one --repo")
    result = validate_local_repo(
        args.validate_local,
        org=org,
        repo=args.repo,
        output_dir=OUTPUT_DIR,
        days_back=args.days,
        remote=args.remote,
    )
    print("\nCommit validation")
    print(render_dataframe(result.commit_summary, args.format))
    if not result.commit_mismatches.empty:
        print("\nCommit mismatches")
        print(render_dataframe(result.commit_mismatches.head(50), args.format))
    print("\nBranch validation")
    print(render_dataframe(result.branch_summary, args.format))
    if not result.branch_mismatches.empty:
        print("\nBranch mismatches")
        print(render_dataframe(result.branch_mismatches.head(50), args.format))


def _handle_delivery_report(args, org):
    """Render the combined delivery report."""
    generate_delivery_report(
        org=org,
        repo=args.repo,
        days_back=args.days,
        output_dir=OUTPUT_DIR,
        branch_active_days=args.branch_active_days,
    )


def _render_pr_report(args, org, con, view_name):
    """Render the selected PR-only report format."""
    if args.repo and args.terminal:
        generate_contributor_report(con, view_name, org, repo=args.repo)
    elif args.terminal:
        generate_rich_terminal_report(con, view_name, org, repo=args.repo, top_n_individual=args.top_n)
    else:
        generate_markdown_report(con, view_name, org, repo=args.repo)


def _handle_pr_report(args, org):
    """Load existing PR data and render a PR report."""
    con, view_name = load_latest_data(org, OUTPUT_DIR, days_back=args.days, repo=args.repo)
    if con is None:
        print("No data available for reporting")
        return

    try:
        count = con.execute(f"SELECT COUNT(*) FROM {view_name}").fetchone()[0]
        repo_filter_msg = f" from {args.repo}" if args.repo else ""
        print(f"🔍 Loaded {count} PRs from last {args.days} days{repo_filter_msg}")
        _render_pr_report(args, org, con, view_name)
    finally:
        con.close()


def _handle_collection(args, org):
    """Collect fresh PR and optional ledger data."""
    print(f"🔍 Collecting PR metrics for {org} (last {args.days} days)")
    repos = _select_repos(args, org)
    if not repos:
        print("No repositories found")
        return

    _collect_prs(args, org, repos)
    _collect_ledger(args, org, repos)


def _apply_output_dir(args):
    """Resolve and apply the process-wide output directory for this CLI invocation."""
    global OUTPUT_DIR
    OUTPUT_DIR = str(resolve_data_lake_dir(args.output_dir))


def _format_bytes(value):
    """Return a compact human-readable byte count."""
    units = ("B", "KiB", "MiB", "GiB")
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024


def _parse_age(value):
    """Parse a simple age string such as 30d, 12h, or seconds."""
    text = str(value).strip().lower()
    if text.endswith("d"):
        return timedelta(days=int(text[:-1]))
    if text.endswith("h"):
        return timedelta(hours=int(text[:-1]))
    return timedelta(seconds=int(text))


def _build_cache_parser():
    """Create parser for `pr-metrics cache ...` management commands."""
    cache_parent = argparse.ArgumentParser(add_help=False)
    cache_parent.add_argument("--cache-dir", default=None, help="Clone cache root override")
    parser = argparse.ArgumentParser(description="Manage pr-metrics clone cache", parents=[cache_parent])
    sub = parser.add_subparsers(dest="cache_command", required=True)
    sub.add_parser("list", parents=[cache_parent], help="List cached clones")
    sub.add_parser("du", parents=[cache_parent], help="Show cache disk usage")
    prune = sub.add_parser("prune", parents=[cache_parent], help="Remove clones older than an age, e.g. 30d")
    prune.add_argument("--older-than", required=True)
    clear = sub.add_parser("clear", parents=[cache_parent], help="Clear all cached clones or a subset")
    clear.add_argument("--org", default=None)
    clear.add_argument("--repo", default=None)
    return parser


def _handle_cache_command(argv):
    """Handle `pr-metrics cache ...` without requiring org/auth."""
    parser = _build_cache_parser()
    args = parser.parse_args(argv)
    cache = CloneCache(resolve_cache_dir(args.cache_dir))
    if args.cache_command == "list":
        for clone in cache.iter_cached_clones():
            accessed = clone.last_accessed.isoformat() if clone.last_accessed else "unknown"
            print(f"{clone.org}/{clone.repo}\t{_format_bytes(clone.bytes_used)}\t{accessed}\t{clone.path}")
    elif args.cache_command == "du":
        print(f"{_format_bytes(cache.du())}\t{cache.cache_root}")
    elif args.cache_command == "prune":
        removed = cache.prune(_parse_age(args.older_than))
        for path in removed:
            print(f"removed\t{path}")
        print(f"Removed {len(removed)} clone(s)")
    elif args.cache_command == "clear":
        removed = cache.clear(org=args.org, repo=args.repo)
        for path in removed:
            print(f"removed\t{path}")
        print(f"Removed {len(removed)} clone(s)")


def main(argv=None):
    """Main CLI entry point."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "cache":
        _handle_cache_command(argv[1:])
        return

    parser = _build_parser()
    args = parser.parse_args(argv)
    _apply_output_dir(args)

    if args.list_insights:
        _handle_list_insights()
        return

    if args.print_skill:
        _handle_print_skill()
        return

    if args.print_skill_bundle:
        _handle_print_skill_bundle()
        return

    try:
        org = resolve_org(args.org)
    except ValueError as exc:
        parser.exit(2, f"error: {exc}\n")

    if args.insight:
        _handle_insight(args, org)
    elif args.validate_local:
        _handle_validate_local(args, org)
    elif args.delivery_report:
        _handle_delivery_report(args, org)
    elif args.report:
        _handle_pr_report(args, org)
    else:
        gh_error = ensure_gh_authenticated()
        if gh_error:
            parser.exit(2, f"error: {gh_error}\n")
        _handle_collection(args, org)


if __name__ == "__main__":
    main()
