#!/usr/bin/env python3
"""Reporting functions for PR metrics using DuckDB."""

import pandas as pd
from datetime import datetime
from tabulate import tabulate
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
from .queries import (
    get_summary_stats, get_author_stats, get_repo_stats,
    get_size_distribution, get_weekly_stats, get_author_weekly_stats,
    get_top_authors, get_monthly_stats
)


def generate_rich_terminal_report(con, view_name="pr_data", org=None, top_n_individual=5):
    """Generate rich terminal-styled report with enhanced UX

    Args:
        con: DuckDB connection
        view_name: Name of the view/table to query
        org: Organization name
        top_n_individual: Number of top contributors to show individual weekly breakdowns for
    """
    if con is None:
        console = Console()
        console.print("[red]No data available for reporting[/red]")
        return

    console = Console()

    # Get summary statistics using DuckDB
    summary = get_summary_stats(con, view_name)
    total_prs, merged_prs, avg_pr_size, avg_merge_time, date_min, date_max, unique_repos, unique_authors = summary

    if total_prs == 0 or date_min is None:
        console.print("[yellow]No PRs found matching the specified criteria[/yellow]")
        return

    merge_rate = (merged_prs / total_prs * 100) if total_prs > 0 else 0
    date_range_start = pd.to_datetime(date_min).strftime('%Y-%m-%d')
    date_range_end = pd.to_datetime(date_max).strftime('%Y-%m-%d')

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
    days_span = (pd.to_datetime(date_max) - pd.to_datetime(date_min)).days + 1
    daily_throughput = total_prs / days_span

    summary_table = Table(show_header=False, box=box.SIMPLE)
    summary_table.add_column("Metric", style="cyan", width=20)
    summary_table.add_column("Value", style="bold green", width=15)
    summary_table.add_column("Detail", style="dim")

    summary_table.add_row("Merged PRs", f"{merged_prs}", f"{merge_rate:.1f}% success rate")
    summary_table.add_row("Avg PR Size", f"{avg_pr_size:.0f} lines", "additions + deletions")
    summary_table.add_row("Avg Merge Time", f"{avg_merge_time or 0:.1f} hours", "from creation to merge")
    summary_table.add_row("Daily Throughput", f"{daily_throughput:.1f} PRs/day", "across all repos")

    console.print(Panel(summary_table, title="🎯 Key Metrics", border_style="green"))

    # Top contributors table
    author_stats_df = get_author_stats(con, view_name)

    authors_table = Table(box=box.ROUNDED)
    authors_table.add_column("Author", style="bold")
    authors_table.add_column("PRs", style="cyan", justify="center")
    authors_table.add_column("Merged", style="green", justify="center")
    authors_table.add_column("Avg Size", style="yellow", justify="right")
    authors_table.add_column("Merge Time", style="magenta", justify="right")
    authors_table.add_column("Success Rate", style="blue", width=25)

    for _, row in author_stats_df.iterrows():
        success_rate = row['merge_rate']
        success_color = "green" if success_rate >= 90 else "yellow" if success_rate >= 70 else "red"

        # Create visual bar for success rate
        bar_length = int(15 * success_rate / 100)
        success_bar = "█" * bar_length + "░" * (15 - bar_length)

        authors_table.add_row(
            row['author'],
            str(int(row['pr_count'])),
            str(int(row['merged_count'])),
            f"{row['avg_pr_size']:.0f}",
            f"{row['avg_merge_time']:.1f}h" if pd.notna(row['avg_merge_time']) else "—",
            f"[{success_color}]{success_bar} {success_rate:.1f}%[/{success_color}]"
        )

    console.print(Panel(authors_table, title="👥 Top Contributors", border_style="cyan"))

    # Repository analytics
    repo_stats_df = get_repo_stats(con, view_name)

    repo_table = Table(box=box.ROUNDED)
    repo_table.add_column("Repository", style="bold")
    repo_table.add_column("PRs", style="cyan", justify="center")
    repo_table.add_column("Contributors", style="blue", justify="center")
    repo_table.add_column("Avg Size", style="yellow", justify="right")
    repo_table.add_column("Merge Time", style="magenta", justify="right")
    repo_table.add_column("Success %", style="green", justify="right")

    for _, row in repo_stats_df.iterrows():
        success_rate = row['merge_rate']
        success_color = "green" if success_rate >= 90 else "yellow" if success_rate >= 70 else "red"

        repo_table.add_row(
            row['repo'],
            str(int(row['pr_count'])),
            str(int(row['contributor_count'])),
            f"{row['avg_pr_size']:.0f}",
            f"{row['avg_merge_time']:.1f}h" if pd.notna(row['avg_merge_time']) else "—",
            f"[{success_color}]{success_rate:.1f}%[/{success_color}]"
        )

    console.print(Panel(repo_table, title="📁 Repository Analytics", border_style="magenta"))

    # PR Size distribution with visual bars
    size_stats_df = get_size_distribution(con, view_name)

    size_table = Table(box=box.ROUNDED)
    size_table.add_column("Size Category", style="bold")
    size_table.add_column("Count", style="cyan", justify="center")
    size_table.add_column("Distribution", style="blue", width=30)
    size_table.add_column("Avg Merge Time", style="magenta", justify="right")

    max_count = size_stats_df['pr_count'].max()
    for _, row in size_stats_df.iterrows():
        count = int(row['pr_count'])
        percentage = count / total_prs * 100
        bar_length = int(20 * count / max_count)
        bar = "█" * bar_length + "░" * (20 - bar_length)

        merge_time = f"{row['avg_merge_time']:.1f}h" if pd.notna(row['avg_merge_time']) else "—"

        size_table.add_row(
            row['size_category'],
            str(count),
            f"{bar} {percentage:.1f}%",
            merge_time
        )

    console.print(Panel(size_table, title="📏 PR Size Distribution", border_style="yellow"))

    # Time-based trends (if enough data)
    days_span = (pd.to_datetime(date_max) - pd.to_datetime(date_min)).days + 1
    if days_span >= 7:
        # Get weekly statistics with enhanced metrics
        weekly_stats_df = get_weekly_stats(con, view_name)

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

        for _, row in weekly_stats_df.iterrows():
            week = pd.to_datetime(row['week'])
            prs_created = int(row['pr_count'])
            prs_merged = int(row['merged_count'])
            merge_rate = row['merge_rate']
            active_authors = int(row['active_authors'])
            prs_per_dev = row['prs_per_dev']
            avg_size = row['avg_pr_size']
            avg_time = row['avg_merge_time']

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
        top_authors_df = get_top_authors(con, limit=top_n_individual, view_name=view_name)

        console.print()  # Add spacing

        for _, author_row in top_authors_df.iterrows():
            author = author_row['author']
            author_weekly_df = get_author_weekly_stats(con, author, view_name)

            # Skip if less than 2 weeks of data
            if len(author_weekly_df) < 2:
                continue

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

            for _, row in author_weekly_df.iterrows():
                week = pd.to_datetime(row['week'])
                prs_created = int(row['pr_count'])
                prs_merged = int(row['merged_count'])
                merge_rate = row['merge_rate']
                avg_size = row['avg_pr_size']
                avg_time = row['avg_merge_time']

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

            # Calculate summary stats for this author
            author_total_stats = con.execute(f"""
                SELECT COUNT(*) as total_prs,
                       SUM(CASE WHEN state = 'merged' THEN 1 ELSE 0 END) as merged_prs
                FROM {view_name}
                WHERE author = '{author}'
            """).fetchone()

            total_prs_author, merged_prs_author = author_total_stats
            overall_rate = (merged_prs_author / total_prs_author * 100) if total_prs_author > 0 else 0

            title = f"👤 {author} ({total_prs_author} PRs, {overall_rate:.1f}% merged)"
            console.print(Panel(author_table, title=title, border_style="cyan", padding=(0, 1)))

    # Footer with tips
    tips_text = """[dim]💡 Tips:[/dim]
• High merge rates indicate healthy review processes
• Large PRs typically take longer to merge and review
• Consistent weekly activity shows steady development pace"""

    console.print(Panel(tips_text, title="📋 Insights", border_style="dim"))

def generate_markdown_report(con, view_name="pr_data", org=None):
    """Generate comprehensive markdown report with detailed analytics using DuckDB"""
    if con is None:
        print("No data available for reporting")
        return

    # Get summary statistics using DuckDB
    summary = get_summary_stats(con, view_name)
    total_prs, merged_prs, avg_pr_size, avg_merge_time, date_min, date_max, unique_repos, unique_authors = summary

    if total_prs == 0 or date_min is None:
        print("No PRs found matching the specified criteria")
        return

    merge_rate = (merged_prs / total_prs * 100) if total_prs > 0 else 0
    date_range_start = pd.to_datetime(date_min).strftime('%Y-%m-%d')
    date_range_end = pd.to_datetime(date_max).strftime('%Y-%m-%d')

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
    print(f"- **Avg PR size**: {avg_pr_size:.0f} lines")
    print(f"- **Avg time to merge**: {avg_merge_time or 0:.1f} hours")

    days_span = (pd.to_datetime(date_max) - pd.to_datetime(date_min)).days + 1
    print(f"- **Daily throughput**: {total_prs / days_span:.1f} PRs/day\n")

    print("## Author Analytics")

    # Get author statistics from DuckDB
    author_stats_df = get_author_stats(con, view_name)

    # Rename columns for display
    author_stats_df.columns = ['Author', 'PRs Created', 'PRs Merged', 'Avg PR Size', 'Avg Merge Time (h)', 'Avg Reviews', 'Merge Rate %']

    print(tabulate(author_stats_df, headers=author_stats_df.columns, tablefmt="pipe", showindex=False))

    print("\n## Time-Based Trends")

    # Weekly analysis
    weekly_stats_df = get_weekly_stats(con, view_name)
    if len(weekly_stats_df) > 0:
        print("\n### Weekly Activity")
        weekly_stats_df['week'] = pd.to_datetime(weekly_stats_df['week']).dt.strftime('%Y-%m-%d')
        weekly_display = weekly_stats_df[['week', 'pr_count', 'merged_count', 'active_authors']]
        weekly_display.columns = ['Week', 'PRs Created', 'PRs Merged', 'Active Authors']
        print(tabulate(weekly_display, headers=weekly_display.columns, tablefmt="pipe", showindex=False))

    # Monthly aggregation if we have enough data
    if days_span >= 30:
        monthly_stats_df = get_monthly_stats(con, view_name)
        print("\n### Monthly Trends")
        monthly_stats_df['month'] = pd.to_datetime(monthly_stats_df['month']).dt.strftime('%Y-%m')
        monthly_stats_df.columns = ['Month', 'PRs Created', 'PRs Merged', 'Active Authors', 'Avg PR Size']
        print(tabulate(monthly_stats_df, headers=monthly_stats_df.columns, tablefmt="pipe", showindex=False))

    print("\n## Repository Analytics")

    # Enhanced repository statistics
    repo_stats_df = get_repo_stats(con, view_name)
    repo_stats_df.columns = ['Repository', 'PRs Created', 'PRs Merged', 'Contributors', 'Avg PR Size', 'Avg Merge Time (h)', 'Merge Rate %']
    print(tabulate(repo_stats_df, headers=repo_stats_df.columns, tablefmt="pipe", showindex=False))

    print("\n## PR Size Distribution")
    size_stats_df = get_size_distribution(con, view_name)
    size_stats_df.columns = ['Size Category', 'Count', 'Avg Merge Time (h)']
    print(tabulate(size_stats_df, headers=size_stats_df.columns, tablefmt="pipe", showindex=False))

