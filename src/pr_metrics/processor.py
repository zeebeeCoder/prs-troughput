#!/usr/bin/env python3
"""Data processing and DataFrame operations."""

import pandas as pd
from pathlib import Path


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


def load_latest_data(org=None, output_dir="output"):
    """Load most recent parquet file, optionally filtered by org"""
    from .utils import sanitize_org_name

    if org:
        sanitized_org = sanitize_org_name(org)
        pattern = f"pr_data_{sanitized_org}_*.parquet"
        files = sorted(Path(output_dir).glob(pattern))
    else:
        files = sorted(Path(output_dir).glob("pr_data_*.parquet"))

    return pd.read_parquet(files[-1]) if files else None
