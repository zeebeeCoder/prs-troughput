#!/usr/bin/env python3
"""CLI entry point for PR metrics tool."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from .github import (
    get_active_repos_from_search,
    get_org_repos,
    get_repo_branches,
    get_repo_commits,
    get_repo_prs,
)
from .insights import INSIGHTS, render_dataframe, run_insight
from .processor import (
    load_latest_data,
    process_branches_to_rows,
    process_commits_to_rows,
    process_prs_to_dataframe,
)
from .reports import (
    generate_contributor_report,
    generate_delivery_report,
    generate_markdown_report,
    generate_rich_terminal_report,
)
from .storage import write_rows_to_hive, write_to_hive
from .utils import resolve_org, sanitize_org_name
from .validation import validate_local_repo


OUTPUT_DIR = "output"


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


def _collect_prs(args, org, repos):
    """Collect and persist PR rows, preserving legacy behavior."""
    all_prs_data = {}
    for i, repo in enumerate(repos, 1):
        repo_name = repo['name']
        print(f"  {i}/{len(repos)} PRs: {repo_name}")
        prs = get_repo_prs(org, repo_name, args.days)
        if prs:
            all_prs_data[repo_name] = prs

    pr_rows = process_prs_to_dataframe(all_prs_data, org)

    if not pr_rows:
        print("No PR data found")
        return []

    # Create DataFrame for analysis (temporary)
    df = pd.DataFrame(pr_rows)

    # Filter repos by minimum PR count unless the user explicitly scoped a repo.
    if not args.repo:
        repo_counts = df['repo'].value_counts()
        active_repos = repo_counts[repo_counts >= args.min_prs].index.tolist()

        if active_repos:
            df = df[df['repo'].isin(active_repos)]
            pr_rows = df.to_dict('records')
            filtered_count = len(repo_counts) - len(active_repos)
            if filtered_count > 0:
                print(f"📊 Filtered out {filtered_count} repos with fewer than {args.min_prs} PRs")
        else:
            print(f"⚠️  No repos found with at least {args.min_prs} PRs")
            return []

    # Calculate and display metrics
    total_prs = len(df)
    merged_prs = len(df[df['state'] == 'merged'])
    merge_rate = (merged_prs / total_prs * 100) if total_prs > 0 else 0

    print("\n🎯 PR RESULTS:")
    print(f"   Total PRs: {total_prs}")
    print(f"   Merged: {merged_prs} ({merge_rate:.1f}%)")
    print(f"   Daily throughput: {merged_prs / args.days:.1f} PRs/day")
    print(f"   Avg PR size: {df['pr_size'].mean():.0f} lines")

    merged_df = df[df['state'] == 'merged']
    if not merged_df.empty:
        print(f"   Avg time to merge: {merged_df['time_to_merge_hours'].mean():.1f} hours")

    print(f"   Top authors: {dict(df['author'].value_counts().head(5))}")

    Path(OUTPUT_DIR).mkdir(exist_ok=True)
    Path(f"{OUTPUT_DIR}/data").mkdir(exist_ok=True)

    sanitized_org = sanitize_org_name(org)
    write_to_hive(pr_rows, sanitized_org, base_dir=f"{OUTPUT_DIR}/data")

    # Also save a legacy CSV backup for compatibility
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_file = f"{OUTPUT_DIR}/pr_data_{sanitized_org}_{timestamp}.csv"
    df.to_csv(csv_file, index=False)

    print(f"\n💾 PR data saved to Hive partitions: {OUTPUT_DIR}/data/")
    print(f"   Legacy CSV backup: {csv_file}")
    return pr_rows


def _collect_ledger(args, org, repos):
    """Collect optional Git delivery ledger datasets."""
    include_commits = args.include_ledger or args.include_commits
    include_branches = args.include_ledger or args.include_branches

    if not (include_commits or include_branches):
        return

    Path(f"{OUTPUT_DIR}/ledger").mkdir(parents=True, exist_ok=True)

    if include_commits:
        all_commits_data = {}
        for i, repo in enumerate(repos, 1):
            repo_name = repo['name']
            print(f"  {i}/{len(repos)} commits: {repo_name}")
            commits = get_repo_commits(
                org,
                repo_name,
                days_back=args.days,
                limit=args.commit_limit,
                include_files=not args.skip_commit_files,
            )
            if commits:
                all_commits_data[repo_name] = commits

        commit_rows, file_rows = process_commits_to_rows(all_commits_data, org)
        write_rows_to_hive(commit_rows, f"{OUTPUT_DIR}/ledger/commits", table_name="commits")
        if not args.skip_commit_files:
            write_rows_to_hive(file_rows, f"{OUTPUT_DIR}/ledger/commit_files", table_name="commit_files")

    if include_branches:
        all_branch_data = {}
        for i, repo in enumerate(repos, 1):
            repo_name = repo['name']
            print(f"  {i}/{len(repos)} branches: {repo_name}")
            branches = get_repo_branches(org, repo_name, limit=args.branch_limit)
            if branches:
                all_branch_data[repo_name] = branches

        branch_rows = process_branches_to_rows(all_branch_data, org)
        write_rows_to_hive(branch_rows, f"{OUTPUT_DIR}/ledger/branches", table_name="branches")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description='Collect PR metrics and Git delivery ledger data using gh + DuckDB')
    parser.add_argument('--days', type=int, default=14, help='Days back to analyze')
    parser.add_argument('--min-prs', type=int, default=3, help='Minimum PRs required to include repo in report (default: 3)')
    parser.add_argument('--full-scan', action='store_true', help='Process all repos instead of just active ones (slower, may hit rate limits)')
    parser.add_argument('--report', action='store_true', help='Generate report from existing data')
    parser.add_argument('--delivery-report', action='store_true', help='Generate combined PR + commit + branch delivery ledger report')
    parser.add_argument('--terminal', action='store_true', help='Generate terminal-friendly report with rich styling')
    parser.add_argument('--org', type=str, help='GitHub organization to analyze (overrides default)')
    parser.add_argument('--repo', type=str, help='Filter by repository name; collection accepts comma-separated names')
    parser.add_argument('--top-n', type=int, default=5, help='Number of top contributors to show individual weekly breakdowns (default: 5)')
    parser.add_argument('--include-ledger', action='store_true', help='Collect commits and branches in addition to PRs')
    parser.add_argument('--include-commits', action='store_true', help='Collect default-branch commit ledger data')
    parser.add_argument('--include-branches', action='store_true', help='Collect remote branch snapshot data')
    parser.add_argument('--commit-limit', type=int, default=100, help='Max default-branch commits to collect per repo (default: 100)')
    parser.add_argument('--branch-limit', type=int, default=100, help='Max branches to collect per repo (default: 100)')
    parser.add_argument('--branch-active-days', type=int, default=30, help='Treat branches with commits in this many days as active WIP (default: 30)')
    parser.add_argument('--skip-commit-files', action='store_true', help='Skip per-file commit facts to reduce GitHub API work')
    parser.add_argument('--list-insights', action='store_true', help='List reusable DuckDB insight slices')
    parser.add_argument('--insight', type=str, help='Run a named insight slice from existing parquet data')
    parser.add_argument('--format', choices=('table', 'json', 'csv'), default='table', help='Output format for --insight (default: table)')
    parser.add_argument('--validate-local', type=str, help='Read-only local Git repo path to compare against existing parquet data')
    parser.add_argument('--remote', type=str, default='origin', help='Remote name for --validate-local branch checks (default: origin)')
    args = parser.parse_args()

    if args.list_insights:
        for name, insight in sorted(INSIGHTS.items()):
            print(f"{name}\t{insight.description}")
        return

    # Resolve organization from CLI args, env var, or default
    org = resolve_org(args.org)

    if args.insight:
        df = run_insight(
            args.insight,
            output_dir=OUTPUT_DIR,
            org=org,
            repo=args.repo,
            days_back=args.days,
        )
        print(render_dataframe(df, args.format))
        return

    if args.validate_local:
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
        return

    if args.report or args.delivery_report:
        if args.delivery_report:
            generate_delivery_report(
                org=org,
                repo=args.repo,
                days_back=args.days,
                output_dir=OUTPUT_DIR,
                branch_active_days=args.branch_active_days,
            )
            return

        # Load with days filter applied during query (more efficient)
        con, view_name = load_latest_data(org, OUTPUT_DIR, days_back=args.days, repo=args.repo)

        if con is not None:
            # Get count for user feedback
            count = con.execute(f"SELECT COUNT(*) FROM {view_name}").fetchone()[0]
            repo_filter_msg = f" from {args.repo}" if args.repo else ""
            print(f"🔍 Loaded {count} PRs from last {args.days} days{repo_filter_msg}")

            try:
                # Route to contributor-focused report when repo is specified
                if args.repo and args.terminal:
                    generate_contributor_report(con, view_name, org, repo=args.repo)
                elif args.terminal:
                    generate_rich_terminal_report(con, view_name, org, repo=args.repo, top_n_individual=args.top_n)
                else:
                    generate_markdown_report(con, view_name, org, repo=args.repo)
            finally:
                # Clean up DuckDB connection
                con.close()
        else:
            print("No data available for reporting")
        return

    print(f"🔍 Collecting PR metrics for {org} (last {args.days} days)")
    repos = _select_repos(args, org)
    if not repos:
        print("No repositories found")
        return

    _collect_prs(args, org, repos)
    _collect_ledger(args, org, repos)


if __name__ == "__main__":
    main()
