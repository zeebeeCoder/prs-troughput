#!/usr/bin/env python3
"""Reporting functions for PR metrics using DuckDB."""

from dataclasses import dataclass
from datetime import datetime

import pandas as pd
from tabulate import tabulate
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
from .queries import (
    get_summary_stats, get_author_stats, get_repo_stats,
    get_size_distribution, get_weekly_stats, get_author_weekly_stats,
    get_top_authors, get_monthly_stats,
    get_contributor_stats_for_repo, get_org_baseline_stats,
    get_contributor_weekly_trends
)
from .processor import load_latest_data
from .storage import load_hive_dataset



def _rate_color(rate, green_at=90, yellow_at=70):
    """Return Rich color for a percentage metric."""
    if rate >= green_at:
        return "green"
    return "yellow" if rate >= yellow_at else "red"


def _duration_color(hours):
    """Return Rich color for merge/review duration."""
    if hours < 24:
        return "green"
    return "yellow" if hours < 72 else "red"


def _success_bar(rate, width=15):
    """Return a unicode bar for a percentage metric."""
    bar_length = int(width * rate / 100)
    return "█" * bar_length + "░" * (width - bar_length)


def _trend_icon(current_count, previous_count, current_rate, previous_rate, stable_count_delta=2):
    """Return a Rich trend icon from count/rate deltas."""
    if previous_count is None:
        return ""
    count_change = current_count - previous_count
    rate_change = current_rate - previous_rate
    rules = (
        ("[green]↑[/green]", count_change > 0 and rate_change >= 0),
        ("[red]↓[/red]", count_change < 0 and rate_change < -5),
        ("[yellow]→[/yellow]", abs(count_change) <= stable_count_delta and abs(rate_change) <= 5),
        ("[yellow]↗[/yellow]", count_change > 0 and rate_change < -5),
        ("[blue]↘[/blue]", count_change < 0 and rate_change > 5),
    )
    return next((icon for icon, matches in rules if matches), "[dim]•[/dim]")


def _summary_context(summary, org=None, repo=None):
    """Convert summary tuple into display-ready report context."""
    total_prs, merged_prs, avg_pr_size, avg_merge_time, date_min, date_max, unique_repos, unique_authors = summary
    date_start = pd.to_datetime(date_min)
    date_end = pd.to_datetime(date_max)
    days_span = (date_end - date_start).days + 1
    return {
        "total_prs": total_prs,
        "merged_prs": merged_prs,
        "avg_pr_size": avg_pr_size,
        "avg_merge_time": avg_merge_time,
        "date_min": date_min,
        "date_max": date_max,
        "unique_repos": unique_repos,
        "unique_authors": unique_authors,
        "merge_rate": (merged_prs / total_prs * 100) if total_prs > 0 else 0,
        "date_range_start": date_start.strftime('%Y-%m-%d'),
        "date_range_end": date_end.strftime('%Y-%m-%d'),
        "days_span": days_span,
        "org_display": f" - {org}" if org else "",
        "repo_display": f" / {repo}" if repo else "",
    }


def _render_rich_overview(console, ctx):
    """Render the dashboard overview panel."""
    header_text = f"""[bold blue]PR Metrics Dashboard{ctx['org_display']}{ctx['repo_display']}[/bold blue]
Generated: [dim]{datetime.now().strftime('%Y-%m-%d %H:%M')}[/dim]

[green]Data Scope:[/green]
• Date Range: {ctx['date_range_start']} to {ctx['date_range_end']}
• Repositories: {ctx['unique_repos']} active repos analyzed
• Contributors: {ctx['unique_authors']} developers
• Total PRs: {ctx['total_prs']}"""
    console.print(Panel(header_text, title="📊 Overview", border_style="blue"))


def _render_key_metrics(console, ctx):
    """Render headline PR metrics."""
    summary_table = Table(show_header=False, box=box.SIMPLE)
    summary_table.add_column("Metric", style="cyan", width=20)
    summary_table.add_column("Value", style="bold green", width=15)
    summary_table.add_column("Detail", style="dim")
    summary_table.add_row("Merged PRs", f"{ctx['merged_prs']}", f"{ctx['merge_rate']:.1f}% success rate")
    summary_table.add_row("Avg PR Size", f"{ctx['avg_pr_size']:.0f} lines", "additions + deletions")
    summary_table.add_row("Avg Merge Time", f"{ctx['avg_merge_time'] or 0:.1f} hours", "from creation to merge")
    summary_table.add_row("Daily Throughput", f"{ctx['total_prs'] / ctx['days_span']:.1f} PRs/day", "across all repos")
    console.print(Panel(summary_table, title="🎯 Key Metrics", border_style="green"))


def _render_top_contributors(console, author_stats_df):
    """Render top contributor summary table."""
    authors_table = Table(box=box.ROUNDED)
    authors_table.add_column("Author", style="bold")
    authors_table.add_column("PRs", style="cyan", justify="center")
    authors_table.add_column("Merged", style="green", justify="center")
    authors_table.add_column("Avg Size", style="yellow", justify="right")
    authors_table.add_column("Merge Time", style="magenta", justify="right")
    authors_table.add_column("Success Rate", style="blue", width=25)
    for _, row in author_stats_df.iterrows():
        success_rate = row['merge_rate']
        color = _rate_color(success_rate)
        authors_table.add_row(
            row['author'],
            str(int(row['pr_count'])),
            str(int(row['merged_count'])),
            f"{row['avg_pr_size']:.0f}",
            f"{row['avg_merge_time']:.1f}h" if pd.notna(row['avg_merge_time']) else "—",
            f"[{color}]{_success_bar(success_rate)} {success_rate:.1f}%[/{color}]",
        )
    console.print(Panel(authors_table, title="👥 Top Contributors", border_style="cyan"))


def _render_repo_analytics(console, repo_stats_df):
    """Render repository analytics table."""
    repo_table = Table(box=box.ROUNDED)
    repo_table.add_column("Repository", style="bold")
    repo_table.add_column("PRs", style="cyan", justify="center")
    repo_table.add_column("Contributors", style="blue", justify="center")
    repo_table.add_column("Avg Size", style="yellow", justify="right")
    repo_table.add_column("Merge Time", style="magenta", justify="right")
    repo_table.add_column("Success %", style="green", justify="right")
    for _, row in repo_stats_df.iterrows():
        success_rate = row['merge_rate']
        color = _rate_color(success_rate)
        repo_table.add_row(
            row['repo'],
            str(int(row['pr_count'])),
            str(int(row['contributor_count'])),
            f"{row['avg_pr_size']:.0f}",
            f"{row['avg_merge_time']:.1f}h" if pd.notna(row['avg_merge_time']) else "—",
            f"[{color}]{success_rate:.1f}%[/{color}]",
        )
    console.print(Panel(repo_table, title="📁 Repository Analytics", border_style="magenta"))


def _render_size_distribution(console, size_stats_df, total_prs):
    """Render PR size distribution table."""
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
        size_table.add_row(row['size_category'], str(count), f"{bar} {percentage:.1f}%", merge_time)
    console.print(Panel(size_table, title="📏 PR Size Distribution", border_style="yellow"))



def _add_columns(table, specs):
    """Add Rich table columns from (name, kwargs) specs."""
    for column, kwargs in specs:
        table.add_column(column, **kwargs)


WEEKLY_PERFORMANCE_COLUMNS = [
    ("Week", {"style": "bold"}),
    ("Created", {"style": "cyan", "justify": "center"}),
    ("Merged", {"style": "green", "justify": "center"}),
    ("Rate", {"style": "blue", "justify": "center"}),
    ("Avg Time", {"style": "magenta", "justify": "right"}),
    ("Contributors", {"style": "yellow", "justify": "center"}),
    ("PRs/Dev", {"style": "white", "justify": "center"}),
    ("Avg Size", {"style": "cyan", "justify": "right"}),
    ("Trend", {"style": "bold", "justify": "center"}),
]


def _weekly_performance_row(row, previous):
    """Return display cells plus next previous state for one weekly row."""
    prs_created = int(row['pr_count'])
    merge_rate = row['merge_rate']
    avg_time = row['avg_merge_time']
    rate_color = _rate_color(merge_rate, green_at=90, yellow_at=75)
    time_display = f"[{_duration_color(avg_time)}]{avg_time:.1f}h[/{_duration_color(avg_time)}]" if pd.notna(avg_time) else "—"
    cells = (
        pd.to_datetime(row['week']).strftime('%Y-%m-%d'),
        str(prs_created),
        str(int(row['merged_count'])),
        f"[{rate_color}]{merge_rate:.1f}%[/{rate_color}]",
        time_display,
        str(int(row['active_authors'])),
        f"{row['prs_per_dev']:.1f}",
        f"{row['avg_pr_size']:.0f}",
        _trend_icon(prs_created, previous[0], merge_rate, previous[1]),
    )
    return cells, (prs_created, merge_rate)


def _render_weekly_performance(console, weekly_stats_df):
    """Render weekly performance trend table."""
    trends_table = Table(box=box.ROUNDED)
    _add_columns(trends_table, WEEKLY_PERFORMANCE_COLUMNS)
    previous = (None, None)
    for _, row in weekly_stats_df.iterrows():
        cells, previous = _weekly_performance_row(row, previous)
        trends_table.add_row(*cells)
    console.print(Panel(trends_table, title="📈 Weekly Performance", border_style="blue"))


def _add_author_week_row(author_table, row, previous):
    """Add one weekly row to an author performance table and return new previous state."""
    prs_created = int(row['pr_count'])
    merge_rate = row['merge_rate']
    trend_icon = _trend_icon(prs_created, previous[0], merge_rate, previous[1], stable_count_delta=1)
    rate_color = _rate_color(merge_rate, green_at=90, yellow_at=75)
    avg_time = row['avg_merge_time']
    time_display = f"[{_duration_color(avg_time)}]{avg_time:.1f}h[/{_duration_color(avg_time)}]" if pd.notna(avg_time) else "—"
    author_table.add_row(
        pd.to_datetime(row['week']).strftime('%Y-%m-%d'),
        str(prs_created),
        str(int(row['merged_count'])),
        f"[{rate_color}]{merge_rate:.1f}%[/{rate_color}]",
        f"{row['avg_pr_size']:.0f}",
        time_display,
        trend_icon,
    )
    return prs_created, merge_rate


def _render_author_weekly_panels(console, con, view_name, top_n_individual):
    """Render individual weekly panels for top contributors."""
    top_authors_df = get_top_authors(con, limit=top_n_individual, view_name=view_name)
    console.print()
    for _, author_row in top_authors_df.iterrows():
        author = author_row['author']
        author_weekly_df = get_author_weekly_stats(con, author, view_name)
        if len(author_weekly_df) < 2:
            continue
        author_table = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
        for column, kwargs in [
            ("Week", {"style": "dim"}),
            ("Created", {"justify": "center"}),
            ("Merged", {"justify": "center"}),
            ("Rate", {"justify": "center"}),
            ("Avg Size", {"justify": "right"}),
            ("Avg Time", {"justify": "right"}),
            ("Trend", {"justify": "center"}),
        ]:
            author_table.add_column(column, **kwargs)
        previous = (None, None)
        for _, row in author_weekly_df.iterrows():
            previous = _add_author_week_row(author_table, row, previous)
        total, merged = con.execute(f"""
            SELECT COUNT(*) as total_prs,
                   SUM(CASE WHEN state = 'merged' THEN 1 ELSE 0 END) as merged_prs
            FROM {view_name}
            WHERE author = '{author}'
        """).fetchone()
        overall_rate = (merged / total * 100) if total > 0 else 0
        title = f"👤 {author} ({total} PRs, {overall_rate:.1f}% merged)"
        console.print(Panel(author_table, title=title, border_style="cyan", padding=(0, 1)))


def _render_report_tips(console):
    """Render closing interpretation hints."""
    tips_text = """[dim]💡 Tips:[/dim]
• High merge rates indicate healthy review processes
• Large PRs typically take longer to merge and review
• Consistent weekly activity shows steady development pace"""
    console.print(Panel(tips_text, title="📋 Insights", border_style="dim"))


def generate_rich_terminal_report(con, view_name="pr_data", org=None, repo=None, top_n_individual=5):
    """Generate rich terminal-styled report with enhanced UX."""
    console = Console()
    if con is None:
        console.print("[red]No data available for reporting[/red]")
        return

    summary = get_summary_stats(con, view_name)
    if summary[0] == 0 or summary[4] is None:
        console.print("[yellow]No PRs found matching the specified criteria[/yellow]")
        return

    ctx = _summary_context(summary, org, repo)
    _render_rich_overview(console, ctx)
    _render_key_metrics(console, ctx)
    _render_top_contributors(console, get_author_stats(con, view_name))
    _render_repo_analytics(console, get_repo_stats(con, view_name))
    _render_size_distribution(console, get_size_distribution(con, view_name), ctx['total_prs'])
    if ctx['days_span'] >= 7:
        _render_weekly_performance(console, get_weekly_stats(con, view_name))
        _render_author_weekly_panels(console, con, view_name, top_n_individual)
    _render_report_tips(console)


def _render_contributor_overview(console, org, repo, ctx):
    """Render contributor report overview."""
    header_text = f"""[bold blue]Contributor Performance Report[/bold blue]
[dim]{org} / {repo}[/dim]
Generated: [dim]{datetime.now().strftime('%Y-%m-%d %H:%M')}[/dim]

[green]Repository Scope:[/green]
• Date Range: {ctx['date_range_start']} to {ctx['date_range_end']} ({ctx['days_span']} days)
• Contributors: {ctx['unique_authors']} developers
• Total PRs: {ctx['total_prs']} ({ctx['merge_rate']:.1f}% merged)"""
    console.print(Panel(header_text, title="📊 Overview", border_style="blue"))


def _render_org_baseline(console, org_baseline):
    """Render organization baseline panel and return its first row, if present."""
    if len(org_baseline) == 0:
        return None
    row = org_baseline.iloc[0]
    baseline_text = f"""[cyan]Organization Averages (for comparison):[/cyan]
• Merge Rate: {row['avg_merge_rate']:.1f}%
• Merge Time: {row['avg_merge_time']:.1f}h
• PR Size: {row['avg_pr_size']:.0f} lines"""
    console.print(Panel(baseline_text, title="📏 Org Baseline", border_style="cyan"))
    return row


def _contributor_comparison(merge_rate, baseline):
    """Return comparison label against organization baseline."""
    if baseline is None:
        return "—"
    org_merge_rate = baseline['avg_merge_rate']
    if merge_rate >= org_merge_rate + 5:
        return "[green]↑ Better[/green]"
    if merge_rate <= org_merge_rate - 5:
        return "[red]↓ Below[/red]"
    return "[yellow]→ Average[/yellow]"


def _format_duration(hours):
    """Format a possibly-null hour value with Rich duration color."""
    if pd.isna(hours):
        return "—"
    display = f"{hours:.1f}h"
    return f"[{_duration_color(hours)}]{display}[/{_duration_color(hours)}]"


def _render_contributor_rankings(console, contributor_stats, baseline):
    """Render contributor ranking table."""
    rankings_table = Table(box=box.ROUNDED, title="Contributor Rankings")
    for column, kwargs in [
        ("Contributor", {"style": "bold"}),
        ("PRs", {"style": "cyan", "justify": "center"}),
        ("Merged", {"style": "green", "justify": "center"}),
        ("Merge Rate", {"style": "blue", "justify": "center"}),
        ("Avg Time", {"style": "magenta", "justify": "right"}),
        ("Avg Size", {"style": "yellow", "justify": "right"}),
        ("Reviews Given", {"style": "purple", "justify": "center"}),
        ("Self-Merge %", {"style": "red", "justify": "center"}),
        ("vs Org", {"style": "bold", "justify": "center"}),
    ]:
        rankings_table.add_column(column, **kwargs)
    for _, row in contributor_stats.iterrows():
        merge_rate = row['merge_rate']
        self_merge_rate = row['self_merge_rate'] if pd.notna(row['self_merge_rate']) else 0.0
        rate_color = _rate_color(merge_rate, green_at=90, yellow_at=75)
        rankings_table.add_row(
            row['author'],
            str(int(row['pr_count'])),
            str(int(row['merged_count'])),
            f"[{rate_color}]{merge_rate:.1f}%[/{rate_color}]",
            _format_duration(row['avg_merge_time']),
            f"{row['avg_pr_size']:.0f}",
            str(int(row['reviews_given'])),
            f"{self_merge_rate:.1f}%",
            _contributor_comparison(merge_rate, baseline),
        )
    console.print(rankings_table)



CONTRIBUTOR_WEEK_COLUMNS = [
    ("Week", {"style": "dim"}),
    ("PRs", {"justify": "center"}),
    ("Merged", {"justify": "center"}),
    ("Rate", {"justify": "center"}),
    ("Avg Size", {"justify": "right"}),
    ("Avg Time", {"justify": "right"}),
    ("Self-Merge", {"justify": "center"}),
    ("Trend", {"justify": "center"}),
]


def _contributor_week_row(row, previous):
    """Return display cells plus next previous state for a contributor week."""
    week_prs = int(row['pr_count'])
    week_rate = row['merge_rate']
    rate_color = _rate_color(week_rate, green_at=90, yellow_at=75)
    cells = (
        pd.to_datetime(row['week']).strftime('%Y-%m-%d'),
        str(week_prs),
        str(int(row['merged_count'])),
        f"[{rate_color}]{week_rate:.1f}%[/{rate_color}]",
        f"{row['avg_pr_size']:.0f}",
        f"{row['avg_merge_time']:.1f}h" if pd.notna(row['avg_merge_time']) else "—",
        str(int(row['self_merged_count'])),
        _trend_icon(week_prs, previous[0], week_rate, previous[1], stable_count_delta=1),
    )
    return cells, (week_prs, week_rate)


def _build_contributor_week_table(weekly_trends):
    """Build a single contributor weekly trend table."""
    table = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
    _add_columns(table, CONTRIBUTOR_WEEK_COLUMNS)
    previous = (None, None)
    for _, row in weekly_trends.iterrows():
        cells, previous = _contributor_week_row(row, previous)
        table.add_row(*cells)
    return table


def _render_contributor_deep_dives(console, con, contributor_stats, repo, view_name):
    """Render top-contributor weekly deep-dive panels."""
    console.print()
    for _, contributor_row in contributor_stats.head(5).iterrows():
        contributor = contributor_row['author']
        weekly_trends = get_contributor_weekly_trends(con, contributor, repo, view_name)
        if len(weekly_trends) < 2:
            continue
        title = f"👤 {contributor} ({int(contributor_row['pr_count'])} PRs, {contributor_row['merge_rate']:.1f}% merged)"
        console.print(Panel(_build_contributor_week_table(weekly_trends), title=title, border_style="cyan", padding=(0, 1)))


def _health_line(value, high, moderate, high_text, moderate_text, good_text):
    """Return a colored health indicator line from threshold bands."""
    if value > high:
        return high_text
    if value > moderate:
        return moderate_text
    return good_text



@dataclass(frozen=True)
class RepositoryHealthMetrics:
    """Derived repository health percentages."""

    contribution_pct: float
    self_merge_rate: float
    review_participation: float


def _repository_health_metrics(contributor_stats, total_prs, merged_prs, unique_authors):
    """Calculate repository health indicators."""
    top_count = max(1, int(len(contributor_stats) * 0.2))
    top_prs = contributor_stats.head(top_count)['pr_count'].sum()
    reviewers_count = len(contributor_stats[contributor_stats['reviews_given'] > 0])
    return RepositoryHealthMetrics(
        contribution_pct=(top_prs / total_prs * 100) if total_prs > 0 else 0,
        self_merge_rate=(contributor_stats['self_merged_count'].sum() / merged_prs * 100) if merged_prs > 0 else 0,
        review_participation=(reviewers_count / unique_authors * 100) if unique_authors > 0 else 0,
    )


def _balance_health_line(contribution_pct):
    """Return contribution-balance health text."""
    return _health_line(
        contribution_pct,
        80,
        60,
        f"⚠️  [red]Bus Factor Risk:[/red] Top 20% of contributors = {contribution_pct:.1f}% of PRs\n",
        f"⚡ [yellow]Moderate Balance:[/yellow] Top 20% of contributors = {contribution_pct:.1f}% of PRs\n",
        f"✓ [green]Good Balance:[/green] Top 20% of contributors = {contribution_pct:.1f}% of PRs\n",
    )


def _self_merge_health_line(self_merge_rate):
    """Return self-merge health text."""
    return _health_line(
        self_merge_rate,
        50,
        25,
        f"⚠️  [red]High Self-Merge Rate:[/red] {self_merge_rate:.1f}% of merged PRs\n",
        f"⚡ [yellow]Moderate Self-Merge:[/yellow] {self_merge_rate:.1f}% of merged PRs\n",
        f"✓ [green]Good Review Culture:[/green] {self_merge_rate:.1f}% self-merged\n",
    )


def _review_participation_health_line(review_participation):
    """Return review-participation health text."""
    if review_participation >= 50:
        return f"✓ [green]Active Review Culture:[/green] {review_participation:.0f}% of contributors review others\n"
    if review_participation >= 25:
        return f"⚡ [yellow]Moderate Review Participation:[/yellow] {review_participation:.0f}% review others\n"
    return f"⚠️  [red]Low Review Participation:[/red] Only {review_participation:.0f}% review others\n"


def _repository_health_text(metrics):
    """Return repository health panel text."""
    return (
        "[bold]Repository Health Indicators:[/bold]\n\n"
        + _balance_health_line(metrics.contribution_pct)
        + _self_merge_health_line(metrics.self_merge_rate)
        + _review_participation_health_line(metrics.review_participation)
    )


def _render_repository_health(console, contributor_stats, total_prs, merged_prs, unique_authors):
    """Render repository health indicators."""
    metrics = _repository_health_metrics(contributor_stats, total_prs, merged_prs, unique_authors)
    console.print()
    console.print(Panel(_repository_health_text(metrics), title="🏥 Health Check", border_style="yellow"))


def generate_contributor_report(con, view_name="pr_data", org=None, repo=None):
    """Generate contributor-focused report for a specific repository."""
    console = Console()
    if con is None:
        console.print("[red]No data available for reporting[/red]")
        return
    if not repo:
        console.print("[red]Repository name required for contributor report[/red]")
        return

    summary = get_summary_stats(con, view_name)
    if summary[0] == 0 or summary[4] is None:
        console.print("[yellow]No PRs found for this repository[/yellow]")
        return

    ctx = _summary_context(summary, org, repo)
    _render_contributor_overview(console, org, repo, ctx)
    baseline = _render_org_baseline(console, get_org_baseline_stats(con, view_name))
    contributor_stats = get_contributor_stats_for_repo(con, org, repo, view_name)
    if len(contributor_stats) == 0:
        console.print("[yellow]No contributor data available[/yellow]")
        return

    _render_contributor_rankings(console, contributor_stats, baseline)
    _render_contributor_deep_dives(console, con, contributor_stats, repo, view_name)
    _render_repository_health(console, contributor_stats, ctx['total_prs'], ctx['merged_prs'], ctx['unique_authors'])



def _print_markdown_header(ctx):
    """Print markdown report title and scope."""
    print(f"# PR Metrics Report{ctx['org_display']}{ctx['repo_display']}")
    print(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n")
    print("## Data Scope")
    print(f"- **Date Range**: {ctx['date_range_start']} to {ctx['date_range_end']}")
    print(f"- **Repositories**: {ctx['unique_repos']} active repos analyzed")
    print(f"- **Authors**: {ctx['unique_authors']} contributors")
    print(f"- **Total PRs**: {ctx['total_prs']}")


def _print_markdown_summary(ctx):
    """Print markdown headline metrics."""
    print("\n## Summary")
    print(f"- **Merged**: {ctx['merged_prs']} ({ctx['merge_rate']:.1f}%)")
    print(f"- **Avg PR size**: {ctx['avg_pr_size']:.0f} lines")
    print(f"- **Avg time to merge**: {ctx['avg_merge_time'] or 0:.1f} hours")
    print(f"- **Daily throughput**: {ctx['total_prs'] / ctx['days_span']:.1f} PRs/day\n")


def _print_markdown_table(title, df, columns=None):
    """Print a markdown table with optional display column names."""
    print(title)
    if columns:
        df = df.copy()
        df.columns = columns
    print(tabulate(df, headers=df.columns, tablefmt="pipe", showindex=False))


def _print_markdown_author_analytics(con, view_name):
    """Print per-author markdown table."""
    author_stats_df = get_author_stats(con, view_name)
    _print_markdown_table(
        "## Author Analytics",
        author_stats_df,
        ['Author', 'PRs Created', 'PRs Merged', 'Avg PR Size', 'Avg Merge Time (h)', 'Avg Reviews', 'Merge Rate %'],
    )


def _print_markdown_time_trends(con, view_name, days_span):
    """Print weekly and monthly markdown trend tables."""
    print("\n## Time-Based Trends")
    weekly_stats_df = get_weekly_stats(con, view_name)
    if len(weekly_stats_df) > 0:
        weekly_stats_df = weekly_stats_df.copy()
        weekly_stats_df['week'] = pd.to_datetime(weekly_stats_df['week']).dt.strftime('%Y-%m-%d')
        weekly_display = weekly_stats_df[['week', 'pr_count', 'merged_count', 'active_authors']]
        _print_markdown_table(
            "\n### Weekly Activity",
            weekly_display,
            ['Week', 'PRs Created', 'PRs Merged', 'Active Authors'],
        )

    if days_span >= 30:
        monthly_stats_df = get_monthly_stats(con, view_name)
        monthly_stats_df = monthly_stats_df.copy()
        monthly_stats_df['month'] = pd.to_datetime(monthly_stats_df['month']).dt.strftime('%Y-%m')
        _print_markdown_table(
            "\n### Monthly Trends",
            monthly_stats_df,
            ['Month', 'PRs Created', 'PRs Merged', 'Active Authors', 'Avg PR Size'],
        )


def _print_markdown_repo_analytics(con, view_name):
    """Print repository analytics markdown table."""
    _print_markdown_table(
        "\n## Repository Analytics",
        get_repo_stats(con, view_name),
        ['Repository', 'PRs Created', 'PRs Merged', 'Contributors', 'Avg PR Size', 'Avg Merge Time (h)', 'Merge Rate %'],
    )


def _print_markdown_size_distribution(con, view_name):
    """Print PR size distribution markdown table."""
    _print_markdown_table(
        "\n## PR Size Distribution",
        get_size_distribution(con, view_name),
        ['Size Category', 'Count', 'Avg Merge Time (h)'],
    )


def generate_markdown_report(con, view_name="pr_data", org=None, repo=None):
    """Generate comprehensive markdown report with detailed analytics using DuckDB."""
    if con is None:
        print("No data available for reporting")
        return

    summary = get_summary_stats(con, view_name)
    if summary[0] == 0 or summary[4] is None:
        print("No PRs found matching the specified criteria")
        return

    ctx = _summary_context(summary, org, repo)
    _print_markdown_header(ctx)
    _print_markdown_summary(ctx)
    _print_markdown_author_analytics(con, view_name)
    _print_markdown_time_trends(con, view_name, ctx['days_span'])
    _print_markdown_repo_analytics(con, view_name)
    _print_markdown_size_distribution(con, view_name)




@dataclass(frozen=True)
class DeliveryReportCounts:
    """Lane counts displayed by the delivery report."""

    merged_prs: int = 0
    open_prs: int = 0
    total_prs: int = 0
    direct_main: int = 0
    total_commits: int = 0
    active_branch_wip: int = 0
    active_invisible_wip: int = 0
    stale_branch_wip: int = 0


def _safe_scalar(con, query, default=0):
    """Run a scalar DuckDB query and return a default on empty/error."""
    try:
        row = con.execute(query).fetchone()
        return row[0] if row and row[0] is not None else default
    except Exception:
        return default


def _dedupe_latest_view(con, source_view, target_view, partition_columns):
    """Create a latest-snapshot view for a ledger dataset."""
    partition_expr = ", ".join(partition_columns)
    con.execute(f"""
        CREATE OR REPLACE VIEW {target_view} AS
        SELECT * EXCLUDE (rn)
        FROM (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY {partition_expr} ORDER BY collected_at DESC) AS rn
            FROM {source_view}
        )
        WHERE rn = 1
    """)
    return target_view


def _load_delivery_sources(org, repo, days_back, output_dir):
    """Load PR, commit, and branch datasets used by the delivery report."""
    pr_con, pr_view = load_latest_data(org, output_dir=output_dir, days_back=days_back, repo=repo)
    commits_con, commits_view = load_hive_dataset(
        f"{output_dir}/ledger/commits",
        "commits",
        org=org,
        repo=repo,
        days_back=days_back,
        date_column="committed_at",
    )
    branches_con, branches_view = load_hive_dataset(
        f"{output_dir}/ledger/branches",
        "branches",
        org=org,
        repo=repo,
        days_back=None,
        date_column=None,
    )
    return pr_con, pr_view, commits_con, commits_view, branches_con, branches_view


def _prepare_delivery_views(commits_con, commits_view, branches_con, branches_view):
    """Dedupe snapshot datasets and return the report-ready view names."""
    if commits_con:
        commits_view = _dedupe_latest_view(
            commits_con,
            commits_view,
            "commits_latest",
            ("org", "repo", "sha"),
        )

    if branches_con:
        branches_view = _dedupe_latest_view(
            branches_con,
            branches_view,
            "branches_latest",
            ("org", "repo", "branch"),
        )

    return commits_view, branches_view


def _active_branch_filter(branch_active_days):
    """Return the SQL predicate for branches treated as active WIP."""
    active_cutoff_expr = f"current_date - INTERVAL {int(branch_active_days)} DAY"
    return f"last_commit_at >= {active_cutoff_expr}"



def _pr_delivery_counts(pr_con, pr_view):
    """Return PR lane counts for the delivery summary."""
    return {
        'merged_prs': _safe_scalar(pr_con, f"SELECT COUNT(*) FROM {pr_view} WHERE state = 'merged'") if pr_con else 0,
        'open_prs': _safe_scalar(pr_con, f"SELECT COUNT(*) FROM {pr_view} WHERE state = 'open'") if pr_con else 0,
        'total_prs': _safe_scalar(pr_con, f"SELECT COUNT(*) FROM {pr_view}") if pr_con else 0,
    }


def _commit_delivery_counts(commits_con, commits_view):
    """Return commit lane counts for the delivery summary."""
    return {
        'direct_main': _safe_scalar(commits_con, f"SELECT COUNT(*) FROM {commits_view} WHERE is_direct_main") if commits_con else 0,
        'total_commits': _safe_scalar(commits_con, f"SELECT COUNT(*) FROM {commits_view}") if commits_con else 0,
    }


def _branch_delivery_counts(branches_con, branches_view, branch_active_days):
    """Return branch WIP lane counts for the delivery summary."""
    if not branches_con:
        return {'active_invisible_wip': 0, 'active_branch_wip': 0, 'stale_branch_wip': 0}
    active_filter = _active_branch_filter(branch_active_days)
    ahead_filter = "COALESCE(ahead_main, 0) > 0"
    return {
        'active_invisible_wip': _safe_scalar(
            branches_con,
            f"SELECT COUNT(*) FROM {branches_view} WHERE {ahead_filter} AND NOT has_open_pr AND {active_filter}",
        ),
        'active_branch_wip': _safe_scalar(
            branches_con,
            f"SELECT COUNT(*) FROM {branches_view} WHERE {ahead_filter} AND {active_filter}",
        ),
        'stale_branch_wip': _safe_scalar(
            branches_con,
            f"SELECT COUNT(*) FROM {branches_view} WHERE {ahead_filter} AND NOT ({active_filter})",
        ),
    }


def _collect_delivery_counts(pr_con, pr_view, commits_con, commits_view, branches_con, branches_view, branch_active_days):
    """Collect lane counts for the combined delivery report."""
    return DeliveryReportCounts(
        **_pr_delivery_counts(pr_con, pr_view),
        **_commit_delivery_counts(commits_con, commits_view),
        **_branch_delivery_counts(branches_con, branches_view, branch_active_days),
    )


def _fetch_activity_mix(commits_con, commits_view):
    """Return commit activity-class counts for the semantic mix panel."""
    if not commits_con:
        return pd.DataFrame()
    return commits_con.execute(f"""
        SELECT activity_class, COUNT(*) AS commits
        FROM {commits_view}
        GROUP BY activity_class
        ORDER BY commits DESC
        LIMIT 12
    """).fetchdf()


def _fetch_active_invisible_wip(branches_con, branches_view, branch_active_days):
    """Return active ahead branches with no open PR."""
    if not branches_con:
        return pd.DataFrame()
    return branches_con.execute(f"""
        SELECT repo, branch, ahead_main, behind_main, last_author, last_commit_at
        FROM {branches_view}
        WHERE COALESCE(ahead_main, 0) > 0
          AND NOT has_open_pr
          AND {_active_branch_filter(branch_active_days)}
        ORDER BY last_commit_at DESC, ahead_main DESC
        LIMIT 15
    """).fetchdf()


def _render_delivery_header(console, repo, days_back, branch_active_days):
    """Render delivery report scope."""
    repo_display = f" / {repo}" if repo else ""
    header = f"""[bold blue]Git Delivery Ledger{repo_display}[/bold blue]
Generated: [dim]{datetime.now().strftime('%Y-%m-%d %H:%M')}[/dim]
Window: [green]last {days_back} days[/green]
Active branch window: [green]{branch_active_days} days[/green]

PRs remain one delivery lane. Direct default-branch commits and active branch WIP are shown beside them."""
    console.print(Panel(header, title="📦 Delivery Scope", border_style="blue"))


def _render_delivery_summary(console, counts, branch_active_days):
    """Render combined throughput lane counts."""
    summary = Table(show_header=False, box=box.SIMPLE)
    summary.add_column("Lane", style="cyan", width=24)
    summary.add_column("Count", style="bold green", justify="right")
    summary.add_column("Meaning", style="dim")
    summary.add_row("Merged PRs", str(counts.merged_prs), f"of {counts.total_prs} PR rows collected")
    summary.add_row("Open PRs", str(counts.open_prs), "review queue / in-flight PR lane")
    summary.add_row("Direct main commits", str(counts.direct_main), f"of {counts.total_commits} default-branch commits")
    summary.add_row("Active Branch WIP", str(counts.active_branch_wip), f"ahead branches touched in {branch_active_days}d")
    summary.add_row("Active Invisible WIP", str(counts.active_invisible_wip), "active ahead branches with no open PR")
    summary.add_row("Stale Branch WIP", str(counts.stale_branch_wip), "ahead branches outside active window")
    console.print(Panel(summary, title="🎯 Combined Throughput", border_style="green"))


def _render_activity_mix(console, activity_df):
    """Render semantic commit activity mix when commit data exists."""
    if activity_df.empty:
        return

    activity = Table(box=box.ROUNDED)
    activity.add_column("Activity", style="bold")
    activity.add_column("Commits", justify="right", style="cyan")
    for _, row in activity_df.iterrows():
        activity.add_row(row['activity_class'] or 'unknown', str(int(row['commits'])))
    console.print(Panel(activity, title="🧬 Semantic Activity Mix", border_style="cyan"))


def _render_invisible_wip(console, invisible_df):
    """Render active invisible WIP rows when branch data exists."""
    if invisible_df.empty:
        return

    invisible = Table(box=box.ROUNDED)
    invisible.add_column("Repo", style="bold")
    invisible.add_column("Branch")
    invisible.add_column("Ahead", justify="right", style="green")
    invisible.add_column("Behind", justify="right", style="yellow")
    invisible.add_column("Author", style="cyan")
    invisible.add_column("Last commit", style="dim")
    for _, row in invisible_df.iterrows():
        last_commit = pd.to_datetime(row['last_commit_at']).strftime('%Y-%m-%d') if pd.notna(row['last_commit_at']) else '—'
        invisible.add_row(
            row['repo'],
            row['branch'],
            str(int(row['ahead_main'] or 0)),
            str(int(row['behind_main'] or 0)),
            row['last_author'] or '—',
            last_commit,
        )
    console.print(Panel(invisible, title="🫥 Active Invisible WIP", border_style="yellow"))


def generate_delivery_report(org=None, repo=None, days_back=14, output_dir="output", branch_active_days=30):
    """Generate a combined PR + commit + branch delivery ledger report."""
    console = Console()
    pr_con = commits_con = branches_con = None
    try:
        pr_con, pr_view, commits_con, commits_view, branches_con, branches_view = _load_delivery_sources(
            org,
            repo,
            days_back,
            output_dir,
        )
        commits_view, branches_view = _prepare_delivery_views(commits_con, commits_view, branches_con, branches_view)
        counts = _collect_delivery_counts(
            pr_con,
            pr_view,
            commits_con,
            commits_view,
            branches_con,
            branches_view,
            branch_active_days,
        )
        activity_df = _fetch_activity_mix(commits_con, commits_view)
        invisible_df = _fetch_active_invisible_wip(branches_con, branches_view, branch_active_days)

        _render_delivery_header(console, repo, days_back, branch_active_days)
        _render_delivery_summary(console, counts, branch_active_days)
        _render_activity_mix(console, activity_df)
        _render_invisible_wip(console, invisible_df)
    finally:
        for con in (pr_con, commits_con, branches_con):
            if con is not None:
                con.close()
