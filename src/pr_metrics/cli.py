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
        # Load with days filter applied during query (more efficient)
        con, view_name = load_latest_data(org, OUTPUT_DIR, days_back=args.days)

        if con is not None:
            # Get count for user feedback
            count = con.execute(f"SELECT COUNT(*) FROM {view_name}").fetchone()[0]
            print(f"🔍 Loaded {count} PRs from last {args.days} days")

            try:
                if args.terminal:
                    generate_rich_terminal_report(con, view_name, org, top_n_individual=args.top_n)
                else:
                    generate_markdown_report(con, view_name, org)
            finally:
                # Clean up DuckDB connection
                con.close()
        else:
            print("No data available for reporting")
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

    # Convert to structured data (list of dicts)
    pr_rows = process_prs_to_dataframe(all_prs_data, org)

    if not pr_rows:
        print("No PR data found")
        return

    # Create DataFrame for analysis (temporary)
    df = pd.DataFrame(pr_rows)

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

    # Save data to Hive partitions
    from .storage import write_to_hive
    from .utils import sanitize_org_name

    Path(OUTPUT_DIR).mkdir(exist_ok=True)
    Path(f"{OUTPUT_DIR}/data").mkdir(exist_ok=True)

    # Write to Hive-partitioned structure
    sanitized_org = sanitize_org_name(org)
    write_to_hive(pr_rows, sanitized_org, base_dir=f"{OUTPUT_DIR}/data")

    # Also save a legacy CSV backup for compatibility
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_file = f"{OUTPUT_DIR}/pr_data_{sanitized_org}_{timestamp}.csv"
    df.to_csv(csv_file, index=False)

    print(f"\n💾 Data saved to Hive partitions: {OUTPUT_DIR}/data/")
    print(f"   Legacy CSV backup: {csv_file}")


if __name__ == "__main__":
    main()
