#!/usr/bin/env python3
"""Data processing with DuckDB backend."""

import pandas as pd
from pathlib import Path
from .storage import write_to_hive, load_data


def extract_commits_count(pr):
    """Extract the number of commits from PR data"""
    commits = pr.get('commits', [])
    return len(commits) if commits else 0


def extract_reviews_data(pr):
    """Extract review count and reviewer list from PR data

    Returns:
        tuple: (review_count, reviewers_string)
    """
    reviews = pr.get('reviews', [])
    if not reviews:
        return 0, ""

    review_count = len(reviews)
    # Get unique reviewer logins
    reviewers = set()
    for review in reviews:
        author = review.get('author', {})
        if author:
            login = author.get('login')
            if login:
                reviewers.add(login)

    reviewers_string = ','.join(sorted(reviewers))
    return review_count, reviewers_string


def calculate_time_to_first_review(pr):
    """Calculate time in hours from PR creation to first review

    Returns:
        float or None: Hours to first review, or None if no reviews
    """
    reviews = pr.get('reviews', [])
    if not reviews:
        return None

    created_at = pd.to_datetime(pr.get('createdAt'))
    if not created_at:
        return None

    # Find earliest review timestamp
    earliest_review = None
    for review in reviews:
        submitted_at = review.get('submittedAt')
        if submitted_at:
            review_time = pd.to_datetime(submitted_at)
            if earliest_review is None or review_time < earliest_review:
                earliest_review = review_time

    if earliest_review:
        time_diff = (earliest_review - created_at).total_seconds() / 3600
        return time_diff

    return None


def extract_merged_by(pr):
    """Extract the login of the user who merged the PR

    Returns:
        str: Login of merge author, or None
    """
    merged_by = pr.get('mergedBy')
    if merged_by and isinstance(merged_by, dict):
        return merged_by.get('login')
    return None


def is_self_merged(pr):
    """Check if PR was merged by its author

    Returns:
        bool: True if author merged their own PR
    """
    author = pr.get('author', {})
    merged_by = pr.get('mergedBy', {})

    if not author or not merged_by:
        return False

    author_login = author.get('login')
    merged_by_login = merged_by.get('login') if isinstance(merged_by, dict) else None

    return author_login == merged_by_login if (author_login and merged_by_login) else False


def process_prs_to_dataframe(all_prs_data, org):
    """Transform all PR data into structured list for DuckDB

    Returns list of dictionaries with partition columns added.
    """
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

            # Extract enhanced data using helper functions
            commits_count = extract_commits_count(pr)
            reviews_count, reviewers_string = extract_reviews_data(pr)
            time_to_first_review = calculate_time_to_first_review(pr)
            merged_by_login = extract_merged_by(pr)
            self_merged = is_self_merged(pr)

            # Get additional fields
            changed_files = pr.get('changedFiles', 0)
            comments = pr.get('comments', [])
            comments_count = len(comments) if comments else 0

            state = 'merged' if merged_at else ('closed' if closed_at else 'open')
            labels = ','.join([l.get('name', '') for l in pr.get('labels', [])])

            # Add partition columns for Hive partitioning
            year = created_at.year if created_at else None
            month = created_at.month if created_at else None

            rows.append({
                'org': org,
                'repo': repo_name,
                'year': year,
                'month': month,
                'pr_number': pr.get('number'),
                'author': author,
                'created_at': created_at,
                'merged_at': merged_at,
                'state': state,
                'pr_size': pr_size,
                'commits': commits_count,
                'reviews': reviews_count,
                'reviewers': reviewers_string,
                'time_to_merge_hours': time_to_merge,
                'time_to_first_review_hours': time_to_first_review,
                'merged_by': merged_by_login,
                'changed_files': changed_files,
                'comments_count': comments_count,
                'self_merged': self_merged,
                'is_draft': pr.get('isDraft', False),
                'labels': labels
            })

    return rows


def load_latest_data(org=None, output_dir="output", days_back=None, repo=None):
    """Load PR data using smart loading strategy

    Tries Hive-partitioned data first, falls back to legacy timestamped files.

    Args:
        org: Organization name to filter (will be used as-is for Hive, sanitized for legacy)
        output_dir: Base directory (contains both 'data/' for Hive and legacy files)
        days_back: Filter to PRs from last N days
        repo: Repository name to filter

    Returns:
        tuple: (DuckDB connection, view_name) or (None, None)
    """
    # Try loading with smart loader (Hive first with original org name, then legacy with sanitized)
    return load_data(
        org=org,  # Use original org name for Hive partitions
        repo=repo,  # Filter by repository if specified
        base_dir=f"{output_dir}/data",
        legacy_dir=output_dir,
        days_back=days_back
    )
