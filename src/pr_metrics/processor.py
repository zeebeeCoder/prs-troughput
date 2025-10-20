#!/usr/bin/env python3
"""Data processing with DuckDB backend."""

import pandas as pd
from pathlib import Path
from .storage import write_to_hive, load_data


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

            # Reviews data might not be available
            time_to_first_review = None

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
                'commits': 0,  # Not available without commits field
                'reviews': 0,  # Not available without reviews field
                'time_to_merge_hours': time_to_merge,
                'time_to_first_review_hours': time_to_first_review,
                'is_draft': pr.get('isDraft', False),
                'labels': labels
            })

    return rows


def load_latest_data(org=None, output_dir="output", days_back=None):
    """Load PR data using smart loading strategy

    Tries Hive-partitioned data first, falls back to legacy timestamped files.

    Args:
        org: Organization name to filter (will be used as-is for Hive, sanitized for legacy)
        output_dir: Base directory (contains both 'data/' for Hive and legacy files)
        days_back: Filter to PRs from last N days

    Returns:
        tuple: (DuckDB connection, view_name) or (None, None)
    """
    # Try loading with smart loader (Hive first with original org name, then legacy with sanitized)
    return load_data(
        org=org,  # Use original org name for Hive partitions
        base_dir=f"{output_dir}/data",
        legacy_dir=output_dir,
        days_back=days_back
    )
