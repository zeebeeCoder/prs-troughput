#!/usr/bin/env python3
"""Reporting functions for PR metrics."""

import pandas as pd
from datetime import datetime
from tabulate import tabulate
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
def generate_rich_terminal_report(df, org=None, top_n_individual=5):
    """Generate rich terminal-styled report with enhanced UX

    Args:
        df: DataFrame with PR data
        org: Organization name
        top_n_individual: Number of top contributors to show individual weekly breakdowns for
    """
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
        df['week'] = df['created_at'].dt.tz_localize(None).dt.to_period('W').dt.start_time

        # Get weekly statistics with enhanced metrics
        weekly_stats = df.groupby('week').agg({
            'pr_number': 'count',
            'state': lambda x: (x == 'merged').sum(),
            'author': 'nunique',
            'pr_size': 'mean',
            'time_to_merge_hours': 'mean'
        }).round(1)

        # Calculate merge rate and PRs per contributor
        weekly_stats['merge_rate'] = (weekly_stats['state'] / weekly_stats['pr_number'] * 100).round(1)
        weekly_stats['prs_per_dev'] = (weekly_stats['pr_number'] / weekly_stats['author']).round(1)

        # Show last 6 weeks
        weekly_stats = weekly_stats.tail(6)

        trends_table = Table(box=box.ROUNDED)
        trends_table.add_column("Week", style="bold")
        trends_table.add_column("Created", style="cyan", justify="center")
        trends_table.add_column("Merged", style="green", justify="center")
        trends_table.add_column("Rate", style="blue", justify="center")
        trends_table.add_column("Avg Time", style="magenta", justify="right")
        trends_table.add_column("Contributors", style="yellow", justify="center")
        trends_table.add_column("PRs/Dev", style="white", justify="center")
        trends_table.add_column("Avg Size", style="cyan", justify="right")
        trends_table.add_column("Trend", style="bold", justify="center")

        # Track previous week's data for trend comparison
        prev_created = None
        prev_merge_rate = None

        for week, row in weekly_stats.iterrows():
            prs_created = int(row['pr_number'])
            prs_merged = int(row['state'])
            merge_rate = row['merge_rate']
            active_authors = int(row['author'])
            prs_per_dev = row['prs_per_dev']
            avg_size = row['pr_size']
            avg_time = row['time_to_merge_hours']

            # Determine trend indicators
            trend_icon = ""
            if prev_created is not None:
                created_change = prs_created - prev_created
                rate_change = merge_rate - prev_merge_rate

                # Overall trend based on volume and quality
                if created_change > 0 and rate_change >= 0:
                    trend_icon = "[green]↑[/green]"  # More PRs, same or better rate
                elif created_change < 0 and rate_change < -5:
                    trend_icon = "[red]↓[/red]"  # Fewer PRs and worse rate
                elif abs(created_change) <= 2 and abs(rate_change) <= 5:
                    trend_icon = "[yellow]→[/yellow]"  # Stable
                elif created_change > 0 and rate_change < -5:
                    trend_icon = "[yellow]↗[/yellow]"  # More PRs but lower quality
                elif created_change < 0 and rate_change > 5:
                    trend_icon = "[blue]↘[/blue]"  # Fewer PRs but better quality
                else:
                    trend_icon = "[dim]•[/dim]"

            # Color-code merge rate
            rate_color = "green" if merge_rate >= 90 else "yellow" if merge_rate >= 75 else "red"

            # Color-code merge time
            time_color = "green" if avg_time < 24 else "yellow" if avg_time < 72 else "red"
            time_display = f"[{time_color}]{avg_time:.1f}h[/{time_color}]" if pd.notna(avg_time) else "—"

            trends_table.add_row(
                week.strftime('%Y-%m-%d'),
                str(prs_created),
                str(prs_merged),
                f"[{rate_color}]{merge_rate:.1f}%[/{rate_color}]",
                time_display,
                str(active_authors),
                f"{prs_per_dev:.1f}",
                f"{avg_size:.0f}",
                trend_icon
            )

            # Store for next iteration
            prev_created = prs_created
            prev_merge_rate = merge_rate

        console.print(Panel(trends_table, title="📈 Weekly Performance", border_style="blue"))

    # Individual contributor weekly performance
    if days_span >= 7:
        top_authors = df['author'].value_counts().head(top_n_individual).index.tolist()

        console.print()  # Add spacing

        for author in top_authors:
            author_df = df[df['author'] == author].copy()
            author_df['week'] = author_df['created_at'].dt.tz_localize(None).dt.to_period('W').dt.start_time

            author_weekly = author_df.groupby('week').agg({
                'pr_number': 'count',
                'state': lambda x: (x == 'merged').sum(),
                'pr_size': 'mean',
                'time_to_merge_hours': 'mean'
            }).round(1)

            # Skip if less than 2 weeks of data
            if len(author_weekly) < 2:
                continue

            author_weekly['merge_rate'] = (author_weekly['state'] / author_weekly['pr_number'] * 100).round(1)
            author_weekly = author_weekly.tail(6)  # Last 6 weeks

            # Create individual table
            author_table = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
            author_table.add_column("Week", style="dim")
            author_table.add_column("Created", justify="center")
            author_table.add_column("Merged", justify="center")
            author_table.add_column("Rate", justify="center")
            author_table.add_column("Avg Size", justify="right")
            author_table.add_column("Avg Time", justify="right")
            author_table.add_column("Trend", justify="center")

            prev_created = None
            prev_rate = None

            for week, row in author_weekly.iterrows():
                prs_created = int(row['pr_number'])
                prs_merged = int(row['state'])
                merge_rate = row['merge_rate']
                avg_size = row['pr_size']
                avg_time = row['time_to_merge_hours']

                # Trend calculation
                trend_icon = ""
                if prev_created is not None:
                    created_change = prs_created - prev_created
                    rate_change = merge_rate - prev_rate

                    if created_change > 0 and rate_change >= 0:
                        trend_icon = "[green]↑[/green]"
                    elif created_change < 0 and rate_change < -5:
                        trend_icon = "[red]↓[/red]"
                    elif abs(created_change) <= 1 and abs(rate_change) <= 5:
                        trend_icon = "[yellow]→[/yellow]"
                    elif created_change > 0 and rate_change < -5:
                        trend_icon = "[yellow]↗[/yellow]"
                    elif created_change < 0 and rate_change > 5:
                        trend_icon = "[blue]↘[/blue]"
                    else:
                        trend_icon = "[dim]•[/dim]"

                # Color coding
                rate_color = "green" if merge_rate >= 90 else "yellow" if merge_rate >= 75 else "red"
                time_color = "green" if avg_time < 24 else "yellow" if avg_time < 72 else "red"
                time_display = f"[{time_color}]{avg_time:.1f}h[/{time_color}]" if pd.notna(avg_time) else "—"

                author_table.add_row(
                    week.strftime('%Y-%m-%d'),
                    str(prs_created),
                    str(prs_merged),
                    f"[{rate_color}]{merge_rate:.1f}%[/{rate_color}]",
                    f"{avg_size:.0f}",
                    time_display,
                    trend_icon
                )

                prev_created = prs_created
                prev_rate = merge_rate

            # Calculate summary stats
            total_prs = author_df['pr_number'].count()
            total_merged = len(author_df[author_df['state'] == 'merged'])
            overall_rate = (total_merged / total_prs * 100) if total_prs > 0 else 0

            title = f"👤 {author} ({total_prs} PRs, {overall_rate:.1f}% merged)"
            console.print(Panel(author_table, title=title, border_style="cyan", padding=(0, 1)))

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

