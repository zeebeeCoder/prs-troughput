#!/usr/bin/env python3
"""Data processing with DuckDB backend."""

from __future__ import annotations

from datetime import datetime, timezone
import re

import pandas as pd

from .storage import load_data
from .parsers import (
    classify_activity,
    extract_spec_name,
    extract_task_id,
    file_extension,
    is_generated_path,
    is_sensitive_path,
    is_test_path,
    parse_conventional_commit,
    top_level_dir,
)


def _parse_dt(value):
    """Parse an optional timestamp into a pandas Timestamp."""
    return pd.to_datetime(value) if value else None


def _walk_values(obj, keys):
    """Yield values for any matching keys found in a nested GitHub JSON shape."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in keys and value is not None:
                yield value
            yield from _walk_values(value, keys)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_values(item, keys)


def _extract_logins(obj):
    """Return sorted unique GitHub logins from nested author/reviewer JSON."""
    logins = set()
    for value in _walk_values(obj, {'login'}):
        if isinstance(value, str) and value:
            logins.add(value)
    return sorted(logins)


def extract_commits_count(pr):
    """Extract the number of commits from PR data"""
    commits = pr.get('commits', [])
    return len(commits) if commits else 0


def extract_reviews_data(pr):
    """Extract review count and reviewer list from PR data

    Returns:
        tuple: (review_count, reviewers_string)
    """
    reviews = pr.get('reviews') or pr.get('latestReviews') or []
    if not reviews:
        return 0, ""

    review_count = len(reviews)
    reviewers_string = ','.join(_extract_logins(reviews))
    return review_count, reviewers_string


def extract_review_request_data(pr):
    """Extract requested reviewer queue fields from PR data."""
    requests = pr.get('reviewRequests') or []
    logins = _extract_logins(requests)
    return len(logins), ','.join(logins)


def calculate_time_to_first_review(pr):
    """Calculate time in hours from PR creation to first review

    Returns:
        float or None: Hours to first review, or None if no reviews
    """
    reviews = pr.get('reviews') or pr.get('latestReviews') or []
    if not reviews:
        return None

    created_at = _parse_dt(pr.get('createdAt'))
    if created_at is None:
        return None

    earliest_review = get_first_review_at(pr)
    if earliest_review is not None:
        time_diff = (earliest_review - created_at).total_seconds() / 3600
        return time_diff

    return None


def get_first_review_at(pr):
    """Return earliest review timestamp, if any."""
    reviews = pr.get('reviews') or pr.get('latestReviews') or []
    timestamps = [_parse_dt(review.get('submittedAt')) for review in reviews if review.get('submittedAt')]
    timestamps = [ts for ts in timestamps if ts is not None]
    return min(timestamps) if timestamps else None


def get_latest_review_at(pr):
    """Return latest review timestamp, if any."""
    reviews = pr.get('reviews') or pr.get('latestReviews') or []
    timestamps = [_parse_dt(review.get('submittedAt')) for review in reviews if review.get('submittedAt')]
    timestamps = [ts for ts in timestamps if ts is not None]
    return max(timestamps) if timestamps else None


def get_review_state_counts(pr):
    """Return approvals and changes-requested counts from reviews."""
    reviews = pr.get('reviews') or pr.get('latestReviews') or []
    approvals = 0
    changes_requested = 0
    for review in reviews:
        state = (review.get('state') or '').upper()
        if state == 'APPROVED':
            approvals += 1
        elif state == 'CHANGES_REQUESTED':
            changes_requested += 1
    return approvals, changes_requested


def extract_ci_summary(pr):
    """Summarize GitHub statusCheckRollup into state and blocker counts."""
    rollup = pr.get('statusCheckRollup') or []
    statuses = [str(value).upper() for value in _walk_values(rollup, {'status', 'state', 'conclusion'}) if value]

    failed = sum(1 for status in statuses if status in {'FAILURE', 'FAILED', 'ERROR', 'TIMED_OUT', 'CANCELLED', 'ACTION_REQUIRED'})
    pending = sum(1 for status in statuses if status in {'PENDING', 'QUEUED', 'IN_PROGRESS', 'WAITING', 'REQUESTED', 'EXPECTED'})

    if failed:
        ci_state = 'failure'
    elif pending:
        ci_state = 'pending'
    elif statuses:
        ci_state = 'success'
    else:
        ci_state = None

    return ci_state, failed, pending


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
    collected_at = pd.Timestamp(datetime.now(timezone.utc))

    for repo_name, prs in all_prs_data.items():
        for pr in prs:
            # Safe data extraction
            author = pr.get('author', {}).get('login', 'unknown') if pr.get('author') else 'unknown'
            created_at = _parse_dt(pr.get('createdAt'))
            merged_at = _parse_dt(pr.get('mergedAt'))
            closed_at = _parse_dt(pr.get('closedAt'))
            updated_at = _parse_dt(pr.get('updatedAt'))

            # Calculate metrics
            additions = pr.get('additions', 0) or 0
            deletions = pr.get('deletions', 0) or 0
            pr_size = additions + deletions
            time_to_merge = (merged_at - created_at).total_seconds() / 3600 if merged_at is not None and created_at is not None else None

            # Extract enhanced data using helper functions
            commits_count = extract_commits_count(pr)
            reviews_count, reviewers_string = extract_reviews_data(pr)
            time_to_first_review = calculate_time_to_first_review(pr)
            merged_by_login = extract_merged_by(pr)
            self_merged = is_self_merged(pr)
            review_request_count, requested_reviewers = extract_review_request_data(pr)
            approvals_count, changes_requested_count = get_review_state_counts(pr)
            ci_state, checks_failed_count, checks_pending_count = extract_ci_summary(pr)
            first_review_at = get_first_review_at(pr)
            latest_review_at = get_latest_review_at(pr)

            # Get additional fields
            changed_files = pr.get('changedFiles', 0)
            comments = pr.get('comments', [])
            comments_count = len(comments) if comments else 0

            state = 'merged' if merged_at is not None else ('closed' if closed_at is not None else 'open')
            labels = ','.join([label.get('name', '') for label in pr.get('labels', [])])
            task_id = extract_task_id(pr.get('title'), pr.get('body'), pr.get('headRefName'))
            spec_name = extract_spec_name(pr.get('title'), pr.get('body'), pr.get('headRefName'))

            # Add partition columns for Hive partitioning
            year = created_at.year if created_at is not None else None
            month = created_at.month if created_at is not None else None

            rows.append({
                'org': org,
                'repo': repo_name,
                'year': year,
                'month': month,
                'collected_at': collected_at,
                'pr_number': pr.get('number'),
                'author': author,
                'title': pr.get('title'),
                'url': pr.get('url'),
                'created_at': created_at,
                'updated_at': updated_at,
                'merged_at': merged_at,
                'closed_at': closed_at,
                'state': state,
                'head_ref': pr.get('headRefName'),
                'base_ref': pr.get('baseRefName'),
                'head_sha': pr.get('headRefOid'),
                'additions': additions,
                'deletions': deletions,
                'pr_size': pr_size,
                'commits': commits_count,
                'reviews': reviews_count,
                'reviewers': reviewers_string,
                'review_decision': pr.get('reviewDecision'),
                'review_request_count': review_request_count,
                'requested_reviewers': requested_reviewers,
                'first_review_at': first_review_at,
                'latest_review_at': latest_review_at,
                'approvals_count': approvals_count,
                'changes_requested_count': changes_requested_count,
                'ci_state': ci_state,
                'checks_failed_count': checks_failed_count,
                'checks_pending_count': checks_pending_count,
                'mergeable': pr.get('mergeable'),
                'merge_state_status': pr.get('mergeStateStatus'),
                'time_to_merge_hours': time_to_merge,
                'time_to_first_review_hours': time_to_first_review,
                'merged_by': merged_by_login,
                'changed_files': changed_files,
                'comments_count': comments_count,
                'self_merged': self_merged,
                'is_draft': pr.get('isDraft', False),
                'labels': labels,
                'task_id': task_id,
                'spec_name': spec_name,
            })

    return rows


def _commit_paths(commit):
    """Extract changed file paths from a commit detail."""
    return [file.get('filename') for file in commit.get('files', []) if file.get('filename')]


def _extract_pr_number_from_subject(subject):
    """Extract GitHub squash/merge PR marker like (#123)."""
    match = re.search(r"\(#(\d+)\)", subject or "")
    return int(match.group(1)) if match else None


def process_commits_to_rows(all_commits_data, org):
    """Transform GitHub commit details into commit and commit-file rows."""
    commit_rows = []
    file_rows = []
    collected_at = pd.Timestamp(datetime.now(timezone.utc))

    for repo_name, commits in all_commits_data.items():
        for commit in commits:
            sha = commit.get('sha')
            commit_obj = commit.get('commit') or {}
            author_obj = commit_obj.get('author') or {}
            committer_obj = commit_obj.get('committer') or {}
            message = commit_obj.get('message') or ''
            subject, _, body = message.partition('\n')
            files = commit.get('files') or []
            paths = _commit_paths(commit)
            conventional_type, conventional_scope = parse_conventional_commit(subject)
            activity_class = classify_activity(subject, paths, conventional_type)
            parent_count = len(commit.get('parents') or [])
            authored_at = _parse_dt(author_obj.get('date'))
            committed_at = _parse_dt(committer_obj.get('date'))
            stats = commit.get('stats') or {}
            task_id = extract_task_id(subject, body, ' '.join(paths))
            spec_name = extract_spec_name(subject, body, ' '.join(paths))
            pr_number = _extract_pr_number_from_subject(subject)

            commit_rows.append({
                'org': org,
                'repo': repo_name,
                'year': committed_at.year if committed_at is not None else None,
                'month': committed_at.month if committed_at is not None else None,
                'collected_at': collected_at,
                'sha': sha,
                'author_name': author_obj.get('name'),
                'author_email': author_obj.get('email'),
                'committer_name': committer_obj.get('name'),
                'committer_email': committer_obj.get('email'),
                'authored_at': authored_at,
                'committed_at': committed_at,
                'subject': subject,
                'body': body.strip() or None,
                'parent_count': parent_count,
                'is_merge_commit': parent_count > 1,
                'is_revert': activity_class == 'revert',
                'branch_refs': 'default',
                'on_main': True,
                'is_direct_main': parent_count == 1 and pr_number is None,
                'pr_number': pr_number,
                'additions': stats.get('additions'),
                'deletions': stats.get('deletions'),
                'changed_files': len(files) if files else None,
                'top_level_dirs': ','.join(sorted({top_level_dir(path) for path in paths if top_level_dir(path)})),
                'file_exts': ','.join(sorted({file_extension(path) for path in paths if file_extension(path)})),
                'task_id': task_id,
                'spec_name': spec_name,
                'conventional_type': conventional_type,
                'conventional_scope': conventional_scope,
                'activity_class': activity_class,
            })

            for file in files:
                path = file.get('filename')
                file_rows.append({
                    'org': org,
                    'repo': repo_name,
                    'year': committed_at.year if committed_at is not None else None,
                    'month': committed_at.month if committed_at is not None else None,
                    'collected_at': collected_at,
                    'sha': sha,
                    'path': path,
                    'status': file.get('status'),
                    'additions': file.get('additions'),
                    'deletions': file.get('deletions'),
                    'top_level_dir': top_level_dir(path),
                    'extension': file_extension(path),
                    'is_test': is_test_path(path),
                    'is_generated': is_generated_path(path),
                    'is_sensitive': is_sensitive_path(path),
                })

    return commit_rows, file_rows


def process_branches_to_rows(all_branch_data, org):
    """Transform branch snapshots into ledger rows."""
    rows = []
    collected_at = pd.Timestamp(datetime.now(timezone.utc))

    for repo_name, branches in all_branch_data.items():
        for branch in branches:
            last_commit_at = _parse_dt(branch.get('last_commit_at'))
            task_id = extract_task_id(branch.get('branch'), branch.get('pr_title'))
            spec_name = extract_spec_name(branch.get('branch'), branch.get('pr_title'))
            rows.append({
                'org': org,
                'repo': repo_name,
                'year': collected_at.year,
                'month': collected_at.month,
                'collected_at': collected_at,
                'branch': branch.get('branch'),
                'head_sha': branch.get('head_sha'),
                'default_branch': branch.get('default_branch'),
                'default_head_sha': branch.get('default_head_sha'),
                'last_commit_at': last_commit_at,
                'last_author': branch.get('last_author'),
                'ahead_main': branch.get('ahead_main'),
                'behind_main': branch.get('behind_main'),
                'has_open_pr': branch.get('has_open_pr', False),
                'pr_number': branch.get('pr_number'),
                'pr_title': branch.get('pr_title'),
                'pr_url': branch.get('pr_url'),
                'task_id': task_id,
                'spec_name': spec_name,
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
