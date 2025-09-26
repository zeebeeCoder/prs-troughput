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
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.columns import Columns
from rich.layout import Layout
from rich import box
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn

OUTPUT_DIR = "output"

def resolve_org(args_org=None):
    """Resolve organization from multiple sources with priority"""
    import os

    # Priority: CLI arg > env var > hardcoded default
    if args_org:
        return args_org

    env_org = os.getenv('PR_METRICS_ORG')
    if env_org:
        return env_org

    # Default fallback
    return "Eve-World-Platform"

def sanitize_org_name(org_name):
    """Sanitize org name for safe filesystem usage"""
    return org_name.lower().replace(' ', '-').replace('_', '-')

def run_gh_command(cmd):
    """Run gh CLI command and return JSON result"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=True)
        return json.loads(result.stdout) if result.stdout.strip() else []
    except subprocess.CalledProcessError as e:
        print(f"Error: {e.stderr}")
        return []

def get_org_repos(org):
    """Get all active repositories in the org (exclude archived and forks)"""
    cmd = f"gh repo list {org} --json name --no-archived --source --limit 100"
    return run_gh_command(cmd)

def get_active_repos_from_search(org, days_back=14):
    """Get repositories that have had PR activity in the specified time period"""
    since_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
    cmd = f'gh search prs --owner {org} --created ">={since_date}" --json repository --limit 1000'

    try:
        prs_data = run_gh_command(cmd)
        if not prs_data:
            print("⚠️  No PRs found via search, falling back to full repo scan")
            return get_org_repos(org)

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
        return get_org_repos(org)

def get_repo_prs(org, repo_name, days_back=14):
    """Get PRs for a repository from the last N days"""
    since_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
    # Don't use --search as it's unreliable; filter in post-processing instead
    cmd = f'gh pr list --repo {org}/{repo_name} --state all --json number,author,title,createdAt,mergedAt,closedAt,reviewDecision,additions,deletions,isDraft,labels --limit 200'
    all_prs = run_gh_command(cmd)

    # Filter PRs by date in post-processing
    filtered_prs = []
    for pr in all_prs:
        if pr.get('createdAt'):
            pr_date = pr['createdAt'][:10]  # Get YYYY-MM-DD part
            if pr_date >= since_date:
                filtered_prs.append(pr)

    return filtered_prs

def process_prs_to_dataframe(all_prs_data, org):
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

            # Reviews data might not be available
            time_to_first_review = None

            state = 'merged' if merged_at else ('closed' if closed_at else 'open')
            labels = ','.join([l.get('name', '') for l in pr.get('labels', [])])

            rows.append({
                'org': org,
                'repo': repo_name,
                'pr_number': pr.get('number'),
                'author': author,
                'created_at': created_at,
                'merged_at': merged_at,
                'state': state,
                'pr_size': pr_size,
                'commits': 0,  # Not available without commits field
                'reviews': 0,  # Not available without reviews field
                'time_to_merge_hours': time_to_merge,
                'time_to_first_review_hours': time_to_first_review,
                'is_draft': pr.get('isDraft', False),
                'labels': labels
            })

    return pd.DataFrame(rows)

def load_latest_data(org=None):
    """Load most recent parquet file, optionally filtered by org"""
    if org:
        sanitized_org = sanitize_org_name(org)
        pattern = f"pr_data_{sanitized_org}_*.parquet"
        files = sorted(Path(OUTPUT_DIR).glob(pattern))
    else:
        files = sorted(Path(OUTPUT_DIR).glob("pr_data_*.parquet"))

    return pd.read_parquet(files[-1]) if files else None

def generate_rich_terminal_report(df, org=None):
    """Generate rich terminal-styled report with enhanced UX"""
    if df is None or df.empty:
        console = Console()
        console.print("[red]No data available for reporting[/red]")
        return

    console = Console()

    # Report header with context
    date_range_start = df['created_at'].min().strftime('%Y-%m-%d')
    date_range_end = df['created_at'].max().strftime('%Y-%m-%d')
    unique_repos = df['repo'].nunique()
    unique_authors = df['author'].nunique()

    total_prs = len(df)
    merged_prs = len(df[df['state'] == 'merged'])
    merge_rate = (merged_prs / total_prs * 100) if total_prs > 0 else 0

    # Get org from data if not provided
    if org is None and 'org' in df.columns:
        org = df['org'].iloc[0]

    org_display = f" - {org}" if org else ""

    # Header panel
    header_text = f"""[bold blue]PR Metrics Dashboard{org_display}[/bold blue]
Generated: [dim]{datetime.now().strftime('%Y-%m-%d %H:%M')}[/dim]

[green]Data Scope:[/green]
• Date Range: {date_range_start} to {date_range_end}
• Repositories: {unique_repos} active repos analyzed
• Contributors: {unique_authors} developers
• Total PRs: {total_prs}"""

    console.print(Panel(header_text, title="📊 Overview", border_style="blue"))

    # Key metrics summary
    merged_df = df[df['state'] == 'merged']
    avg_merge_time = merged_df['time_to_merge_hours'].mean() if not merged_df.empty else 0
    days_span = (df['created_at'].max() - df['created_at'].min()).days + 1
    daily_throughput = total_prs / days_span

    summary_table = Table(show_header=False, box=box.SIMPLE)
    summary_table.add_column("Metric", style="cyan", width=20)
    summary_table.add_column("Value", style="bold green", width=15)
    summary_table.add_column("Detail", style="dim")

    summary_table.add_row("Merged PRs", f"{merged_prs}", f"{merge_rate:.1f}% success rate")
    summary_table.add_row("Avg PR Size", f"{df['pr_size'].mean():.0f} lines", "additions + deletions")
    summary_table.add_row("Avg Merge Time", f"{avg_merge_time:.1f} hours", "from creation to merge")
    summary_table.add_row("Daily Throughput", f"{daily_throughput:.1f} PRs/day", "across all repos")

    console.print(Panel(summary_table, title="🎯 Key Metrics", border_style="green"))

    # Top contributors table
    author_stats = df.groupby('author').agg({
        'pr_number': 'count',
        'state': lambda x: (x == 'merged').sum(),
        'pr_size': 'mean',
        'time_to_merge_hours': 'mean',
        'reviews': 'mean'
    }).round(1)

    author_stats['merge_rate'] = (author_stats['state'] / author_stats['pr_number'] * 100).round(1)
    author_stats = author_stats.sort_values('pr_number', ascending=False)

    authors_table = Table(box=box.ROUNDED)
    authors_table.add_column("Author", style="bold")
    authors_table.add_column("PRs", style="cyan", justify="center")
    authors_table.add_column("Merged", style="green", justify="center")
    authors_table.add_column("Avg Size", style="yellow", justify="right")
    authors_table.add_column("Merge Time", style="magenta", justify="right")
    authors_table.add_column("Success Rate", style="blue", width=25)

    for author, row in author_stats.iterrows():
        success_rate = row['merge_rate']
        success_color = "green" if success_rate >= 90 else "yellow" if success_rate >= 70 else "red"

        # Create visual bar for success rate
        bar_length = int(15 * success_rate / 100)
        success_bar = "█" * bar_length + "░" * (15 - bar_length)

        authors_table.add_row(
            author,
            str(int(row['pr_number'])),
            str(int(row['state'])),
            f"{row['pr_size']:.0f}",
            f"{row['time_to_merge_hours']:.1f}h" if pd.notna(row['time_to_merge_hours']) else "—",
            f"[{success_color}]{success_bar} {success_rate:.1f}%[/{success_color}]"
        )

    console.print(Panel(authors_table, title="👥 Top Contributors", border_style="cyan"))

    # Repository analytics
    repo_stats = df.groupby('repo').agg({
        'pr_number': 'count',
        'state': lambda x: (x == 'merged').sum(),
        'author': 'nunique',
        'pr_size': 'mean',
        'time_to_merge_hours': 'mean'
    }).round(1)

    repo_stats['merge_rate'] = (repo_stats['state'] / repo_stats['pr_number'] * 100).round(1)
    repo_stats = repo_stats.sort_values('pr_number', ascending=False)

    repo_table = Table(box=box.ROUNDED)
    repo_table.add_column("Repository", style="bold")
    repo_table.add_column("PRs", style="cyan", justify="center")
    repo_table.add_column("Contributors", style="blue", justify="center")
    repo_table.add_column("Avg Size", style="yellow", justify="right")
    repo_table.add_column("Merge Time", style="magenta", justify="right")
    repo_table.add_column("Success %", style="green", justify="right")

    for repo, row in repo_stats.iterrows():
        success_rate = row['merge_rate']
        success_color = "green" if success_rate >= 90 else "yellow" if success_rate >= 70 else "red"

        repo_table.add_row(
            repo,
            str(int(row['pr_number'])),
            str(int(row['author'])),
            f"{row['pr_size']:.0f}",
            f"{row['time_to_merge_hours']:.1f}h" if pd.notna(row['time_to_merge_hours']) else "—",
            f"[{success_color}]{success_rate:.1f}%[/{success_color}]"
        )

    console.print(Panel(repo_table, title="📁 Repository Analytics", border_style="magenta"))

    # PR Size distribution with visual bars
    df['size_category'] = pd.cut(df['pr_size'], bins=[0, 50, 200, float('inf')],
                                labels=['Small (<50)', 'Medium (50-200)', 'Large (>200)'])
    size_stats = df.groupby('size_category', observed=True).agg({
        'pr_number': 'count',
        'time_to_merge_hours': 'mean'
    }).round(1)

    size_table = Table(box=box.ROUNDED)
    size_table.add_column("Size Category", style="bold")
    size_table.add_column("Count", style="cyan", justify="center")
    size_table.add_column("Distribution", style="blue", width=30)
    size_table.add_column("Avg Merge Time", style="magenta", justify="right")

    max_count = size_stats['pr_number'].max()
    for category, row in size_stats.iterrows():
        count = int(row['pr_number'])
        percentage = count / total_prs * 100
        bar_length = int(20 * count / max_count)
        bar = "█" * bar_length + "░" * (20 - bar_length)

        merge_time = f"{row['time_to_merge_hours']:.1f}h" if pd.notna(row['time_to_merge_hours']) else "—"

        size_table.add_row(
            str(category),
            str(count),
            f"{bar} {percentage:.1f}%",
            merge_time
        )

    console.print(Panel(size_table, title="📏 PR Size Distribution", border_style="yellow"))

    # Time-based trends (if enough data)
    days_span = (df['created_at'].max() - df['created_at'].min()).days + 1
    if days_span >= 7:
        df['week'] = df['created_at'].dt.to_period('W').dt.start_time
        weekly_stats = df.groupby('week').agg({
            'pr_number': 'count',
            'state': lambda x: (x == 'merged').sum(),
            'author': 'nunique'
        }).tail(6)  # Show last 6 weeks

        trends_table = Table(box=box.ROUNDED)
        trends_table.add_column("Week", style="bold")
        trends_table.add_column("PRs Created", style="cyan", justify="center")
        trends_table.add_column("PRs Merged", style="green", justify="center")
        trends_table.add_column("Active Authors", style="blue", justify="center")
        trends_table.add_column("Activity", style="yellow", width=20)

        max_prs = weekly_stats['pr_number'].max()
        for week, row in weekly_stats.iterrows():
            prs_created = int(row['pr_number'])
            prs_merged = int(row['state'])
            active_authors = int(row['author'])

            activity_bar_length = int(15 * prs_created / max_prs)
            activity_bar = "█" * activity_bar_length + "░" * (15 - activity_bar_length)

            trends_table.add_row(
                week.strftime('%Y-%m-%d'),
                str(prs_created),
                str(prs_merged),
                str(active_authors),
                activity_bar
            )

        console.print(Panel(trends_table, title="📈 Weekly Trends", border_style="blue"))

    # Footer with tips
    tips_text = """[dim]💡 Tips:[/dim]
• High merge rates indicate healthy review processes
• Large PRs typically take longer to merge and review
• Consistent weekly activity shows steady development pace"""

    console.print(Panel(tips_text, title="📋 Insights", border_style="dim"))

def generate_markdown_report(df, org=None):
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

    # Get org from data if not provided
    if org is None and 'org' in df.columns:
        org = df['org'].iloc[0]

    org_display = f" - {org}" if org else ""

    print(f"# PR Metrics Report{org_display}")
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
    parser.add_argument('--terminal', action='store_true', help='Generate terminal-friendly report with rich styling')
    parser.add_argument('--org', type=str, help='GitHub organization to analyze (overrides default)')
    args = parser.parse_args()

    # Resolve organization from CLI args, env var, or default
    org = resolve_org(args.org)

    if args.report:
        if args.terminal:
            generate_rich_terminal_report(load_latest_data(org), org)
        else:
            generate_markdown_report(load_latest_data(org), org)
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