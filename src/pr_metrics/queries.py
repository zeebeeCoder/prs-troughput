#!/usr/bin/env python3
"""DuckDB SQL queries for PR metrics analytics."""


def get_summary_stats(con, view_name="pr_data"):
    """Get overall summary statistics"""
    query = f"""
    SELECT
        COUNT(*) as total_prs,
        SUM(CASE WHEN state = 'merged' THEN 1 ELSE 0 END) as merged_prs,
        ROUND(AVG(pr_size), 0) as avg_pr_size,
        ROUND(AVG(CASE WHEN state = 'merged' THEN time_to_merge_hours END), 1) as avg_merge_time,
        MIN(created_at) as date_min,
        MAX(created_at) as date_max,
        COUNT(DISTINCT repo) as unique_repos,
        COUNT(DISTINCT author) as unique_authors
    FROM {view_name}
    """
    return con.execute(query).fetchone()


def get_author_stats(con, view_name="pr_data"):
    """Get per-author statistics"""
    query = f"""
    SELECT
        author,
        COUNT(*) as pr_count,
        SUM(CASE WHEN state = 'merged' THEN 1 ELSE 0 END) as merged_count,
        ROUND(AVG(pr_size), 1) as avg_pr_size,
        ROUND(AVG(CASE WHEN state = 'merged' THEN time_to_merge_hours END), 1) as avg_merge_time,
        ROUND(AVG(reviews), 1) as avg_reviews,
        ROUND(100.0 * SUM(CASE WHEN state = 'merged' THEN 1 ELSE 0 END) / COUNT(*), 1) as merge_rate
    FROM {view_name}
    GROUP BY author
    ORDER BY pr_count DESC
    """
    return con.execute(query).fetchdf()


def get_repo_stats(con, view_name="pr_data"):
    """Get per-repository statistics"""
    query = f"""
    SELECT
        repo,
        COUNT(*) as pr_count,
        SUM(CASE WHEN state = 'merged' THEN 1 ELSE 0 END) as merged_count,
        COUNT(DISTINCT author) as contributor_count,
        ROUND(AVG(pr_size), 1) as avg_pr_size,
        ROUND(AVG(CASE WHEN state = 'merged' THEN time_to_merge_hours END), 1) as avg_merge_time,
        ROUND(100.0 * SUM(CASE WHEN state = 'merged' THEN 1 ELSE 0 END) / COUNT(*), 1) as merge_rate
    FROM {view_name}
    GROUP BY repo
    ORDER BY pr_count DESC
    """
    return con.execute(query).fetchdf()


def get_size_distribution(con, view_name="pr_data"):
    """Get PR size distribution statistics"""
    query = f"""
    SELECT
        CASE
            WHEN pr_size <= 50 THEN 'Small (<50)'
            WHEN pr_size <= 200 THEN 'Medium (50-200)'
            ELSE 'Large (>200)'
        END as size_category,
        COUNT(*) as pr_count,
        ROUND(AVG(CASE WHEN state = 'merged' THEN time_to_merge_hours END), 1) as avg_merge_time
    FROM {view_name}
    GROUP BY size_category
    ORDER BY
        CASE size_category
            WHEN 'Small (<50)' THEN 1
            WHEN 'Medium (50-200)' THEN 2
            ELSE 3
        END
    """
    return con.execute(query).fetchdf()


def get_weekly_stats(con, view_name="pr_data"):
    """Get weekly aggregated statistics"""
    query = f"""
    SELECT
        DATE_TRUNC('week', created_at) as week,
        COUNT(*) as pr_count,
        SUM(CASE WHEN state = 'merged' THEN 1 ELSE 0 END) as merged_count,
        COUNT(DISTINCT author) as active_authors,
        ROUND(AVG(pr_size), 1) as avg_pr_size,
        ROUND(AVG(CASE WHEN state = 'merged' THEN time_to_merge_hours END), 1) as avg_merge_time,
        ROUND(100.0 * SUM(CASE WHEN state = 'merged' THEN 1 ELSE 0 END) / COUNT(*), 1) as merge_rate,
        ROUND(COUNT(*) * 1.0 / COUNT(DISTINCT author), 1) as prs_per_dev
    FROM {view_name}
    GROUP BY week
    ORDER BY week DESC
    LIMIT 6
    """
    return con.execute(query).fetchdf()


def get_author_weekly_stats(con, author, view_name="pr_data"):
    """Get weekly statistics for a specific author"""
    query = f"""
    SELECT
        DATE_TRUNC('week', created_at) as week,
        COUNT(*) as pr_count,
        SUM(CASE WHEN state = 'merged' THEN 1 ELSE 0 END) as merged_count,
        ROUND(AVG(pr_size), 1) as avg_pr_size,
        ROUND(AVG(CASE WHEN state = 'merged' THEN time_to_merge_hours END), 1) as avg_merge_time,
        ROUND(100.0 * SUM(CASE WHEN state = 'merged' THEN 1 ELSE 0 END) / COUNT(*), 1) as merge_rate
    FROM {view_name}
    WHERE author = '{author}'
    GROUP BY week
    ORDER BY week DESC
    LIMIT 6
    """
    return con.execute(query).fetchdf()


def get_top_authors(con, limit=5, view_name="pr_data"):
    """Get list of top N authors by PR count"""
    query = f"""
    SELECT author, COUNT(*) as pr_count
    FROM {view_name}
    GROUP BY author
    ORDER BY pr_count DESC
    LIMIT {limit}
    """
    return con.execute(query).fetchdf()


def get_monthly_stats(con, view_name="pr_data"):
    """Get monthly aggregated statistics"""
    query = f"""
    SELECT
        DATE_TRUNC('month', created_at) as month,
        COUNT(*) as pr_count,
        SUM(CASE WHEN state = 'merged' THEN 1 ELSE 0 END) as merged_count,
        COUNT(DISTINCT author) as active_authors,
        ROUND(AVG(pr_size), 1) as avg_pr_size
    FROM {view_name}
    GROUP BY month
    ORDER BY month
    """
    return con.execute(query).fetchdf()
