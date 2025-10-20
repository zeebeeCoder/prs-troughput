#!/usr/bin/env python3
"""CLI entry point for PR metrics tool."""

import argparse
from datetime import timedelta
from pathlib import Path
import pandas as pd

from .github import get_org_repos, get_active_repos_from_search, get_repo_prs
from .processor import process_prs_to_dataframe, load_latest_data
from .reports import generate_rich_terminal_report, generate_markdown_report
from .utils import resolve_org, sanitize_org_name


OUTPUT_DIR = "output"


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description='Collect PR metrics using pandas')
    parser.add_argument('--days', type=int, default=14, help='Days back to analyze')
    parser.add_argument('--min-prs', type=int, default=3, help='Minimum PRs required to include repo in report (default: 3)')
    parser.add_argument('--full-scan', action='store_true', help='Process all repos instead of just active ones (slower, may hit rate limits)')
    parser.add_argument('--report', action='store_true', help='Generate report from existing data')
    parser.add_argument('--terminal', action='store_true', help='Generate terminal-friendly report with rich styling')
    parser.add_argument('--org', type=str, help='GitHub organization to analyze (overrides default)')
    parser.add_argument('--top-n', type=int, default=5, help='Number of top contributors to show individual weekly breakdowns (default: 5)')
    args = parser.parse_args()

    # Resolve organization from CLI args, env var, or default
    org = resolve_org(args.org)

    if args.report:
        df = load_latest_data(org, OUTPUT_DIR)

        # Filter data by time window if --days is specified
        if df is not None and not df.empty and args.days:
            cutoff_date = pd.Timestamp.now(tz='UTC') - timedelta(days=args.days)
            df = df[df['created_at'] >= cutoff_date]
            print(f"🔍 Filtering report data to last {args.days} days")

        if args.terminal:
            generate_rich_terminal_report(df, org, top_n_individual=args.top_n)
        else:
            generate_markdown_report(df, org)
        return

    print(f"🔍 Collecting PR metrics for {org} (last {args.days} days)")

    # Get repos - active repos by default, full scan if requested
    if args.full_scan:
        repos = get_org_repos(org)
        print(f"📁 Processing {len(repos)} repositories (full scan)")
    else:
        repos = get_active_repos_from_search(org, args.days)

    all_prs_data = {}
    for i, repo in enumerate(repos, 1):
        repo_name = repo['name']
        print(f"  {i}/{len(repos)}: {repo_name}")
        prs = get_repo_prs(org, repo_name, args.days)
        if prs:
            all_prs_data[repo_name] = prs

    # Convert to DataFrame
    df = process_prs_to_dataframe(all_prs_data, org)

    if df.empty:
        print("No PR data found")
        return

    # Filter repos by minimum PR count
    repo_counts = df['repo'].value_counts()
    active_repos = repo_counts[repo_counts >= args.min_prs].index.tolist()

    if active_repos:
        df = df[df['repo'].isin(active_repos)]
        filtered_count = len(repo_counts) - len(active_repos)
        if filtered_count > 0:
            print(f"📊 Filtered out {filtered_count} repos with fewer than {args.min_prs} PRs")
    else:
        print(f"⚠️  No repos found with at least {args.min_prs} PRs")
        return

    # Calculate and display metrics
    total_prs = len(df)
    merged_prs = len(df[df['state'] == 'merged'])
    merge_rate = (merged_prs / total_prs * 100) if total_prs > 0 else 0

    print(f"\n🎯 RESULTS:")
    print(f"   Total PRs: {total_prs}")
    print(f"   Merged: {merged_prs} ({merge_rate:.1f}%)")
    print(f"   Daily throughput: {merged_prs / args.days:.1f} PRs/day")
    print(f"   Avg PR size: {df['pr_size'].mean():.0f} lines")

    merged_df = df[df['state'] == 'merged']
    if not merged_df.empty:
        print(f"   Avg time to merge: {merged_df['time_to_merge_hours'].mean():.1f} hours")

    print(f"   Top authors: {dict(df['author'].value_counts().head(5))}")

    # Save data
    Path(OUTPUT_DIR).mkdir(exist_ok=True)
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sanitized_org = sanitize_org_name(org)

    parquet_file = f"{OUTPUT_DIR}/pr_data_{sanitized_org}_{timestamp}.parquet"
    csv_file = f"{OUTPUT_DIR}/pr_data_{sanitized_org}_{timestamp}.csv"

    df.to_parquet(parquet_file, index=False)
    df.to_csv(csv_file, index=False)

    print(f"\n💾 Data saved:")
    print(f"   {parquet_file}")
    print(f"   {csv_file}")


if __name__ == "__main__":
    main()
