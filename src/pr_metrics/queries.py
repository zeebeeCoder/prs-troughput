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


def get_contributor_stats_for_repo(con, org, repo, view_name="pr_data"):
    """Get detailed per-contributor statistics for a specific repository

    Args:
        con: DuckDB connection
        org: Organization name
        repo: Repository name
        view_name: Name of the view/table to query

    Returns:
        DataFrame with contributor metrics including reviews given, self-merge rate, etc.
    """
    # Check which columns exist
    columns = [col[0] for col in con.execute(f"DESCRIBE {view_name}").fetchall()]

    # Build CTE with available columns
    cte_fields = [
        "author",
        "COUNT(*) as pr_count",
        "SUM(CASE WHEN state = 'merged' THEN 1 ELSE 0 END) as merged_count",
        "ROUND(AVG(pr_size), 1) as avg_pr_size",
        "ROUND(AVG(CASE WHEN state = 'merged' THEN time_to_merge_hours END), 1) as avg_merge_time",
        "ROUND(100.0 * SUM(CASE WHEN state = 'merged' THEN 1 ELSE 0 END) / COUNT(*), 1) as merge_rate"
    ]

    if 'changed_files' in columns:
        cte_fields.append("ROUND(AVG(changed_files), 1) as avg_files_changed")
    else:
        cte_fields.append("NULL as avg_files_changed")

    if 'time_to_first_review_hours' in columns:
        cte_fields.append("ROUND(AVG(CASE WHEN state = 'merged' THEN time_to_first_review_hours END), 1) as avg_time_to_first_review")
    else:
        cte_fields.append("NULL as avg_time_to_first_review")

    if 'self_merged' in columns:
        cte_fields.append("SUM(CASE WHEN self_merged THEN 1 ELSE 0 END) as self_merged_count")
    else:
        cte_fields.append("0 as self_merged_count")

    # Handle reviewers field
    if 'reviewers' in columns:
        review_cte = f"""
        review_counts AS (
            SELECT
                TRIM(reviewer) as reviewer,
                COUNT(*) as reviews_given
            FROM {view_name}
            CROSS JOIN UNNEST(STRING_SPLIT(reviewers, ',')) AS t(reviewer)
            WHERE org = '{org}' AND repo = '{repo}' AND reviewers != ''
            GROUP BY TRIM(reviewer)
        )
        """
        join_clause = "LEFT JOIN review_counts rc ON cp.author = rc.reviewer"
        reviews_field = "COALESCE(rc.reviews_given, 0) as reviews_given"
    else:
        review_cte = ""
        join_clause = ""
        reviews_field = "0 as reviews_given"

    query = f"""
    WITH contributor_prs AS (
        SELECT
            {', '.join(cte_fields)}
        FROM {view_name}
        WHERE org = '{org}' AND repo = '{repo}'
        GROUP BY author
    ){', ' + review_cte if review_cte else ''}
    SELECT
        cp.author,
        cp.pr_count,
        cp.merged_count,
        cp.merge_rate,
        cp.avg_pr_size,
        cp.avg_merge_time,
        cp.avg_files_changed,
        cp.avg_time_to_first_review,
        {reviews_field},
        cp.self_merged_count,
        ROUND(100.0 * cp.self_merged_count / NULLIF(cp.merged_count, 0), 1) as self_merge_rate
    FROM contributor_prs cp
    {join_clause}
    ORDER BY cp.pr_count DESC
    """
    return con.execute(query).fetchdf()


def get_org_baseline_stats(con, view_name="pr_data"):
    """Get organization-wide baseline statistics for comparison

    Returns:
        Single row DataFrame with org averages
    """
    # Check which columns exist
    columns = [col[0] for col in con.execute(f"DESCRIBE {view_name}").fetchall()]

    # Build query with only available columns
    query_parts = [
        "ROUND(100.0 * SUM(CASE WHEN state = 'merged' THEN 1 ELSE 0 END) / COUNT(*), 1) as avg_merge_rate",
        "ROUND(AVG(CASE WHEN state = 'merged' THEN time_to_merge_hours END), 1) as avg_merge_time",
        "ROUND(AVG(pr_size), 1) as avg_pr_size",
        "ROUND(AVG(reviews), 1) as avg_reviews"
    ]

    if 'changed_files' in columns:
        query_parts.append("ROUND(AVG(changed_files), 1) as avg_files_changed")
    else:
        query_parts.append("NULL as avg_files_changed")

    if 'time_to_first_review_hours' in columns:
        query_parts.append("ROUND(AVG(CASE WHEN state = 'merged' THEN time_to_first_review_hours END), 1) as avg_time_to_first_review")
    else:
        query_parts.append("NULL as avg_time_to_first_review")

    query = f"""
    SELECT
        {', '.join(query_parts)}
    FROM {view_name}
    """
    return con.execute(query).fetchdf()


def get_contributor_review_activity(con, view_name="pr_data"):
    """Get review activity across all contributors

    Returns:
        DataFrame showing who reviews most actively
    """
    query = f"""
    SELECT
        TRIM(reviewer) as reviewer,
        COUNT(DISTINCT repo) as repos_reviewed,
        COUNT(*) as reviews_given,
        COUNT(DISTINCT author) as developers_reviewed
    FROM {view_name}
    CROSS JOIN UNNEST(STRING_SPLIT(reviewers, ',')) AS t(reviewer)
    WHERE reviewers != ''
    GROUP BY TRIM(reviewer)
    ORDER BY reviews_given DESC
    """
    return con.execute(query).fetchdf()


def get_contributor_weekly_trends(con, author, repo, view_name="pr_data"):
    """Get weekly activity trends for a specific contributor in a repository

    Args:
        con: DuckDB connection
        author: Contributor login
        repo: Repository name
        view_name: Name of the view/table to query

    Returns:
        DataFrame with weekly metrics
    """
    # Check which columns exist
    columns = [col[0] for col in con.execute(f"DESCRIBE {view_name}").fetchall()]

    # Build query with available columns
    select_fields = [
        "DATE_TRUNC('week', created_at) as week",
        "COUNT(*) as pr_count",
        "SUM(CASE WHEN state = 'merged' THEN 1 ELSE 0 END) as merged_count",
        "ROUND(AVG(pr_size), 1) as avg_pr_size",
        "ROUND(AVG(CASE WHEN state = 'merged' THEN time_to_merge_hours END), 1) as avg_merge_time",
        "ROUND(100.0 * SUM(CASE WHEN state = 'merged' THEN 1 ELSE 0 END) / COUNT(*), 1) as merge_rate"
    ]

    if 'self_merged' in columns:
        select_fields.append("SUM(CASE WHEN self_merged THEN 1 ELSE 0 END) as self_merged_count")
    else:
        select_fields.append("0 as self_merged_count")

    query = f"""
    SELECT
        {', '.join(select_fields)}
    FROM {view_name}
    WHERE author = '{author}' AND repo = '{repo}'
    GROUP BY week
    ORDER BY week DESC
    LIMIT 12
    """
    return con.execute(query).fetchdf()
