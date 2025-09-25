#!/usr/bin/env python3
"""
Simple PR metrics collector using pandas for efficient processing
"""

import subprocess
import json
import argparse
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from tabulate import tabulate

ORG = "Eve-World-Platform"
OUTPUT_DIR = "output"

def run_gh_command(cmd):
    """Run gh CLI command and return JSON result"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=True)
        return json.loads(result.stdout) if result.stdout.strip() else []
    except subprocess.CalledProcessError as e:
        print(f"Error: {e.stderr}")
        return []

def get_org_repos():
    """Get all active repositories in the org (exclude archived and forks)"""
    cmd = f"gh repo list {ORG} --json name --no-archived --source --limit 100"
    return run_gh_command(cmd)

def get_active_repos_from_search(days_back=14):
    """Get repositories that have had PR activity in the specified time period"""
    since_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
    cmd = f'gh search prs --owner {ORG} --created ">={since_date}" --json repository --limit 1000'

    try:
        prs_data = run_gh_command(cmd)
        if not prs_data:
            print("⚠️  No PRs found via search, falling back to full repo scan")
            return get_org_repos()

        # Extract unique repository names
        repo_names = set()
        for pr in prs_data:
            if pr.get('repository', {}).get('name'):
                repo_names.add(pr['repository']['name'])

        # Convert to expected format (list of dicts with 'name' key)
        active_repos = [{'name': name} for name in sorted(repo_names)]

        print(f"🎯 Found {len(active_repos)} repositories with recent PR activity")
        return active_repos

    except Exception as e:
        print(f"⚠️  Search failed ({e}), falling back to full repo scan")
        return get_org_repos()

def get_repo_prs(repo_name, days_back=14):
    """Get PRs for a repository from the last N days"""
    since_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
    cmd = f'gh pr list --repo {ORG}/{repo_name} --state all --json number,author,title,createdAt,mergedAt,closedAt,reviewDecision,additions,deletions,commits,reviews,isDraft,labels --search "created:>={since_date}"'
    return run_gh_command(cmd)

def process_prs_to_dataframe(all_prs_data):
    """Transform all PR data into a single pandas DataFrame"""
    rows = []

    for repo_name, prs in all_prs_data.items():
        for pr in prs:
            # Safe data extraction
            author = pr.get('author', {}).get('login', 'unknown') if pr.get('author') else 'unknown'
            created_at = pd.to_datetime(pr.get('createdAt')) if pr.get('createdAt') else None
            merged_at = pd.to_datetime(pr.get('mergedAt')) if pr.get('mergedAt') else None
            closed_at = pd.to_datetime(pr.get('closedAt')) if pr.get('closedAt') else None

            # Calculate metrics
            pr_size = (pr.get('additions', 0) or 0) + (pr.get('deletions', 0) or 0)
            time_to_merge = (merged_at - created_at).total_seconds() / 3600 if merged_at and created_at else None

            reviews = pr.get('reviews', [])
            time_to_first_review = None
            if reviews and created_at:
                first_review_at = pd.to_datetime(reviews[0].get('submittedAt'))
                if first_review_at:
                    time_to_first_review = (first_review_at - created_at).total_seconds() / 3600

            state = 'merged' if merged_at else ('closed' if closed_at else 'open')
            labels = ','.join([l.get('name', '') for l in pr.get('labels', [])])

            rows.append({
                'repo': repo_name,
                'pr_number': pr.get('number'),
                'author': author,
                'created_at': created_at,
                'merged_at': merged_at,
                'state': state,
                'pr_size': pr_size,
                'commits': len(pr.get('commits', [])),
                'reviews': len(reviews),
                'time_to_merge_hours': time_to_merge,
                'time_to_first_review_hours': time_to_first_review,
                'is_draft': pr.get('isDraft', False),
                'labels': labels
            })

    return pd.DataFrame(rows)

def load_latest_data():
    """Load most recent parquet file"""
    files = sorted(Path(OUTPUT_DIR).glob("*.parquet"))
    return pd.read_parquet(files[-1]) if files else None

def generate_markdown_report(df):
    """Generate comprehensive markdown report with detailed analytics"""
    if df is None or df.empty:
        print("No data available for reporting")
        return

    # Report context and scope
    date_range_start = df['created_at'].min().strftime('%Y-%m-%d')
    date_range_end = df['created_at'].max().strftime('%Y-%m-%d')
    unique_repos = df['repo'].nunique()
    unique_authors = df['author'].nunique()

    total_prs = len(df)
    merged_prs = len(df[df['state'] == 'merged'])
    merge_rate = (merged_prs / total_prs * 100) if total_prs > 0 else 0

    print("# PR Metrics Report")
    print(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n")

    print("## Data Scope")
    print(f"- **Date Range**: {date_range_start} to {date_range_end}")
    print(f"- **Repositories**: {unique_repos} active repos analyzed")
    print(f"- **Authors**: {unique_authors} contributors")
    print(f"- **Total PRs**: {total_prs}")

    print("\n## Summary")
    print(f"- **Merged**: {merged_prs} ({merge_rate:.1f}%)")
    print(f"- **Avg PR size**: {df['pr_size'].mean():.0f} lines")

    merged_df = df[df['state'] == 'merged']
    if not merged_df.empty:
        print(f"- **Avg time to merge**: {merged_df['time_to_merge_hours'].mean():.1f} hours")

    days_span = (df['created_at'].max() - df['created_at'].min()).days + 1
    print(f"- **Daily throughput**: {total_prs / days_span:.1f} PRs/day\n")

    print("## Author Analytics")

    # Comprehensive author statistics
    author_stats = df.groupby('author').agg({
        'pr_number': 'count',
        'state': lambda x: (x == 'merged').sum(),
        'pr_size': 'mean',
        'time_to_merge_hours': 'mean',
        'reviews': 'mean'
    }).round(1)

    # Calculate merge rates
    author_stats['merge_rate'] = (author_stats['state'] / author_stats['pr_number'] * 100).round(1)

    # Rename columns
    author_stats.columns = ['PRs Created', 'PRs Merged', 'Avg PR Size', 'Avg Merge Time (h)', 'Avg Reviews', 'Merge Rate %']

    # Sort by PR count descending
    author_stats = author_stats.sort_values('PRs Created', ascending=False)

    print(tabulate(author_stats, headers=author_stats.columns, tablefmt="pipe"))

    print("\n## Time-Based Trends")

    # Weekly analysis
    df['week'] = df['created_at'].dt.to_period('W').dt.start_time
    weekly_stats = df.groupby('week').agg({
        'pr_number': 'count',
        'state': lambda x: (x == 'merged').sum(),
        'author': 'nunique'
    })
    weekly_stats.columns = ['PRs Created', 'PRs Merged', 'Active Authors']
    weekly_stats.index = weekly_stats.index.strftime('%Y-%m-%d')

    if len(weekly_stats) > 0:
        print("\n### Weekly Activity")
        print(tabulate(weekly_stats, headers=weekly_stats.columns, tablefmt="pipe"))

    # Monthly aggregation if we have enough data
    if days_span >= 30:
        df['month'] = df['created_at'].dt.to_period('M').dt.start_time
        monthly_stats = df.groupby('month').agg({
            'pr_number': 'count',
            'state': lambda x: (x == 'merged').sum(),
            'author': 'nunique',
            'pr_size': 'mean'
        }).round(1)
        monthly_stats.columns = ['PRs Created', 'PRs Merged', 'Active Authors', 'Avg PR Size']
        monthly_stats.index = monthly_stats.index.strftime('%Y-%m')

        print("\n### Monthly Trends")
        print(tabulate(monthly_stats, headers=monthly_stats.columns, tablefmt="pipe"))

    print("\n## Repository Analytics")

    # Enhanced repository statistics
    repo_stats = df.groupby('repo').agg({
        'pr_number': 'count',
        'state': lambda x: (x == 'merged').sum(),
        'author': 'nunique',
        'pr_size': 'mean',
        'time_to_merge_hours': 'mean'
    }).round(1)

    # Calculate merge rates
    repo_stats['merge_rate'] = (repo_stats['state'] / repo_stats['pr_number'] * 100).round(1)

    # Rename columns
    repo_stats.columns = ['PRs Created', 'PRs Merged', 'Contributors', 'Avg PR Size', 'Avg Merge Time (h)', 'Merge Rate %']

    # Sort by PR count descending
    repo_stats = repo_stats.sort_values('PRs Created', ascending=False)

    print(tabulate(repo_stats, headers=repo_stats.columns, tablefmt="pipe"))

    print("\n## PR Size Distribution")
    df['size_category'] = pd.cut(df['pr_size'], bins=[0, 50, 200, float('inf')],
                                labels=['Small', 'Medium', 'Large'])
    size_stats = df.groupby('size_category', observed=True).agg({
        'pr_number': 'count',
        'time_to_merge_hours': 'mean'
    }).round(1)
    size_stats.columns = ['Count', 'Avg Merge Time (h)']
    print(tabulate(size_stats, headers=size_stats.columns, tablefmt="pipe"))

def main():
    parser = argparse.ArgumentParser(description='Collect PR metrics using pandas')
    parser.add_argument('--days', type=int, default=14, help='Days back to analyze')
    parser.add_argument('--min-prs', type=int, default=3, help='Minimum PRs required to include repo in report (default: 3)')
    parser.add_argument('--full-scan', action='store_true', help='Process all repos instead of just active ones (slower, may hit rate limits)')
    parser.add_argument('--report', action='store_true', help='Generate report from existing data')
    args = parser.parse_args()

    if args.report:
        generate_markdown_report(load_latest_data())
        return

    print(f"🔍 Collecting PR metrics for {ORG} (last {args.days} days)")

    # Get repos - active repos by default, full scan if requested
    if args.full_scan:
        repos = get_org_repos()
        print(f"📁 Processing {len(repos)} repositories (full scan)")
    else:
        repos = get_active_repos_from_search(args.days)

    all_prs_data = {}
    for i, repo in enumerate(repos, 1):
        repo_name = repo['name']
        print(f"  {i}/{len(repos)}: {repo_name}")
        prs = get_repo_prs(repo_name, args.days)
        if prs:
            all_prs_data[repo_name] = prs

    # Convert to DataFrame
    df = process_prs_to_dataframe(all_prs_data)

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
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    parquet_file = f"{OUTPUT_DIR}/pr_data_{ORG.lower()}_{timestamp}.parquet"
    csv_file = f"{OUTPUT_DIR}/pr_data_{ORG.lower()}_{timestamp}.csv"

    df.to_parquet(parquet_file, index=False)
    df.to_csv(csv_file, index=False)

    print(f"\n💾 Data saved:")
    print(f"   {parquet_file}")
    print(f"   {csv_file}")

if __name__ == "__main__":
    main()