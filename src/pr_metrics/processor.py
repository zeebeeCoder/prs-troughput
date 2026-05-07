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



def _pr_author_login(pr):
    """Return a PR author login with the legacy unknown fallback."""
    return pr.get('author', {}).get('login', 'unknown') if pr.get('author') else 'unknown'


def _pr_state(merged_at, closed_at):
    """Map PR lifecycle timestamps to the stored state label."""
    if merged_at is not None:
        return 'merged'
    return 'closed' if closed_at is not None else 'open'


def _timestamp_partition(value):
    """Return year/month partition values for an optional timestamp."""
    if value is None:
        return None, None
    return value.year, value.month


def _pr_labels(pr):
    """Return comma-separated PR label names."""
    return ','.join([label.get('name', '') for label in pr.get('labels', [])])



def _pr_timestamps(pr):
    """Return parsed PR lifecycle timestamps."""
    return {
        'created_at': _parse_dt(pr.get('createdAt')),
        'updated_at': _parse_dt(pr.get('updatedAt')),
        'merged_at': _parse_dt(pr.get('mergedAt')),
        'closed_at': _parse_dt(pr.get('closedAt')),
    }


def _pr_size_fields(pr):
    """Return PR size fields."""
    additions = pr.get('additions', 0) or 0
    deletions = pr.get('deletions', 0) or 0
    return {'additions': additions, 'deletions': deletions, 'pr_size': additions + deletions}


def _pr_review_fields(pr):
    """Return PR review, reviewer queue, and CI summary fields."""
    reviews_count, reviewers_string = extract_reviews_data(pr)
    review_request_count, requested_reviewers = extract_review_request_data(pr)
    approvals_count, changes_requested_count = get_review_state_counts(pr)
    ci_state, checks_failed_count, checks_pending_count = extract_ci_summary(pr)
    return {
        'reviews': reviews_count,
        'reviewers': reviewers_string,
        'review_decision': pr.get('reviewDecision'),
        'review_request_count': review_request_count,
        'requested_reviewers': requested_reviewers,
        'first_review_at': get_first_review_at(pr),
        'latest_review_at': get_latest_review_at(pr),
        'approvals_count': approvals_count,
        'changes_requested_count': changes_requested_count,
        'ci_state': ci_state,
        'checks_failed_count': checks_failed_count,
        'checks_pending_count': checks_pending_count,
    }


def _pr_traceability_fields(pr):
    """Return task/spec traceability fields for a PR."""
    return {
        'task_id': extract_task_id(pr.get('title'), pr.get('body'), pr.get('headRefName')),
        'spec_name': extract_spec_name(pr.get('title'), pr.get('body'), pr.get('headRefName')),
    }


def _pr_timing_fields(pr, timestamps):
    """Return derived PR timing fields."""
    created_at = timestamps['created_at']
    merged_at = timestamps['merged_at']
    return {
        'time_to_merge_hours': (merged_at - created_at).total_seconds() / 3600 if merged_at is not None and created_at is not None else None,
        'time_to_first_review_hours': calculate_time_to_first_review(pr),
    }


def _pr_identity_fields(org, repo_name, pr, collected_at, created_at):
    """Return PR identity and partition fields."""
    year, month = _timestamp_partition(created_at)
    return {
        'org': org,
        'repo': repo_name,
        'year': year,
        'month': month,
        'collected_at': collected_at,
        'pr_number': pr.get('number'),
        'author': _pr_author_login(pr),
        'title': pr.get('title'),
        'url': pr.get('url'),
    }


def _pr_branch_fields(pr):
    """Return PR branch pointer fields."""
    return {
        'head_ref': pr.get('headRefName'),
        'base_ref': pr.get('baseRefName'),
        'head_sha': pr.get('headRefOid'),
    }


def _pr_misc_fields(pr):
    """Return remaining PR metadata fields."""
    return {
        'commits': extract_commits_count(pr),
        'mergeable': pr.get('mergeable'),
        'merge_state_status': pr.get('mergeStateStatus'),
        'merged_by': extract_merged_by(pr),
        'changed_files': pr.get('changedFiles', 0),
        'comments_count': len(pr.get('comments') or []),
        'self_merged': is_self_merged(pr),
        'is_draft': pr.get('isDraft', False),
        'labels': _pr_labels(pr),
    }


def _build_pr_row(org, repo_name, pr, collected_at):
    """Transform one GitHub PR object into a storage row."""
    timestamps = _pr_timestamps(pr)
    return {
        **_pr_identity_fields(org, repo_name, pr, collected_at, timestamps['created_at']),
        **timestamps,
        'state': _pr_state(timestamps['merged_at'], timestamps['closed_at']),
        **_pr_branch_fields(pr),
        **_pr_size_fields(pr),
        **_pr_review_fields(pr),
        **_pr_timing_fields(pr, timestamps),
        **_pr_misc_fields(pr),
        **_pr_traceability_fields(pr),
    }


def process_prs_to_dataframe(all_prs_data, org):
    """Transform all PR data into structured list for DuckDB.

    Returns list of dictionaries with partition columns added.
    """
    collected_at = pd.Timestamp(datetime.now(timezone.utc))
    return [
        _build_pr_row(org, repo_name, pr, collected_at)
        for repo_name, prs in all_prs_data.items()
        for pr in prs
    ]


def _commit_paths(commit):
    """Extract changed file paths from a commit detail."""
    return [file.get('filename') for file in commit.get('files', []) if file.get('filename')]


def _extract_pr_number_from_subject(subject):
    """Extract GitHub squash/merge PR marker like (#123)."""
    match = re.search(r"\(#(\d+)\)", subject or "")
    return int(match.group(1)) if match else None



def _commit_message_parts(commit_obj):
    """Split a GitHub commit message into subject and body."""
    message = commit_obj.get('message') or ''
    subject, _, body = message.partition('\n')
    return subject, body


def _commit_path_summary(paths):
    """Return compact directory and extension summaries for commit paths."""
    return {
        'top_level_dirs': ','.join(sorted({top_level_dir(path) for path in paths if top_level_dir(path)})),
        'file_exts': ','.join(sorted({file_extension(path) for path in paths if file_extension(path)})),
    }



def _commit_core_fields(org, repo_name, commit, collected_at, committed_at):
    """Return stable identity and partition fields for a commit row."""
    year, month = _timestamp_partition(committed_at)
    return {
        'org': org,
        'repo': repo_name,
        'year': year,
        'month': month,
        'collected_at': collected_at,
        'sha': commit.get('sha'),
    }


def _commit_actor_fields(commit_obj, committed_at):
    """Return author/committer fields for a commit row."""
    author_obj = commit_obj.get('author') or {}
    committer_obj = commit_obj.get('committer') or {}
    return {
        'author_name': author_obj.get('name'),
        'author_email': author_obj.get('email'),
        'committer_name': committer_obj.get('name'),
        'committer_email': committer_obj.get('email'),
        'authored_at': _parse_dt(author_obj.get('date')),
        'committed_at': committed_at,
    }


def _commit_change_fields(commit, files, paths):
    """Return size and path summary fields for a commit row."""
    stats = commit.get('stats') or {}
    path_summary = _commit_path_summary(paths)
    return {
        'additions': stats.get('additions'),
        'deletions': stats.get('deletions'),
        'changed_files': len(files) if files else None,
        'top_level_dirs': path_summary['top_level_dirs'],
        'file_exts': path_summary['file_exts'],
    }


def _commit_traceability_fields(subject, body, paths):
    """Return task/spec traceability fields for a commit row."""
    searchable_paths = ' '.join(paths)
    return {
        'task_id': extract_task_id(subject, body, searchable_paths),
        'spec_name': extract_spec_name(subject, body, searchable_paths),
    }


def _commit_message_fields(subject, body, conventional_type, conventional_scope, activity_class):
    """Return message/classification fields for a commit row."""
    return {
        'subject': subject,
        'body': body.strip() or None,
        'conventional_type': conventional_type,
        'conventional_scope': conventional_scope,
        'activity_class': activity_class,
    }


def _commit_sources(commit, fallback_pr_number=None):
    """Return normalized source observations for a commit row."""
    sources = list(commit.get('_ledger_sources') or [])
    if sources:
        return sources
    return [{
        'source_kind': 'default_branch',
        'source_id': 'default',
        'pr_number': fallback_pr_number,
        'branch': None,
        'evidence': 'legacy_default_branch_commit',
    }]


def _commit_pr_number(subject_pr_number, sources):
    """Resolve the best PR number evidence for a commit."""
    for source in sources:
        if source.get('pr_number') is not None:
            return source.get('pr_number')
    return subject_pr_number


def _source_kinds(sources):
    """Return a sorted compact source-kind list for canonical commit rows."""
    return ','.join(sorted({source.get('source_kind') for source in sources if source.get('source_kind')}))


def _branch_refs(sources):
    """Return a sorted compact branch-ref list for canonical commit rows."""
    branches = {source.get('branch') for source in sources if source.get('branch')}
    if any(source.get('source_kind') == 'default_branch' for source in sources):
        branches.add('default')
    return ','.join(sorted(branches))


def _on_main(sources):
    """Return whether a commit was observed on the default branch."""
    return any(source.get('source_kind') == 'default_branch' for source in sources)


def _build_commit_row(org, repo_name, commit, collected_at):
    """Transform one GitHub commit detail into a canonical commit ledger row."""
    commit_obj = commit.get('commit') or {}
    committer_obj = commit_obj.get('committer') or {}
    subject, body = _commit_message_parts(commit_obj)
    files = commit.get('files') or []
    paths = _commit_paths(commit)
    conventional_type, conventional_scope = parse_conventional_commit(subject)
    activity_class = classify_activity(subject, paths, conventional_type)
    parent_count = len(commit.get('parents') or [])
    committed_at = _parse_dt(committer_obj.get('date'))
    subject_pr_number = _extract_pr_number_from_subject(subject)
    sources = _commit_sources(commit, fallback_pr_number=subject_pr_number)
    pr_number = _commit_pr_number(subject_pr_number, sources)
    on_main = _on_main(sources)

    return {
        **_commit_core_fields(org, repo_name, commit, collected_at, committed_at),
        **_commit_actor_fields(commit_obj, committed_at),
        **_commit_message_fields(subject, body, conventional_type, conventional_scope, activity_class),
        'parent_count': parent_count,
        'is_merge_commit': parent_count > 1,
        'is_revert': activity_class == 'revert',
        'source_kinds': _source_kinds(sources),
        'branch_refs': _branch_refs(sources),
        'on_main': on_main,
        'is_direct_main': _is_direct_main(parent_count, pr_number, on_main),
        'pr_number': pr_number,
        **_commit_change_fields(commit, files, paths),
        **_commit_traceability_fields(subject, body, paths),
    }


def _is_direct_main(parent_count, pr_number, on_main=True):
    """Return whether a default-branch commit appears unlinked from a PR."""
    return bool(on_main and parent_count == 1 and pr_number is None)


def _build_commit_file_row(org, repo_name, commit, file, committed_at, collected_at):
    """Transform one changed file from a commit detail into a file-fact row."""
    path = file.get('filename')
    year, month = _timestamp_partition(committed_at)
    return {
        'org': org,
        'repo': repo_name,
        'year': year,
        'month': month,
        'collected_at': collected_at,
        'sha': commit.get('sha'),
        'path': path,
        'status': file.get('status'),
        'additions': file.get('additions'),
        'deletions': file.get('deletions'),
        'top_level_dir': top_level_dir(path),
        'extension': file_extension(path),
        'is_test': is_test_path(path),
        'is_generated': is_generated_path(path),
        'is_sensitive': is_sensitive_path(path),
    }


def _build_commit_file_rows(org, repo_name, commit, collected_at):
    """Transform all file facts for one commit detail."""
    commit_obj = commit.get('commit') or {}
    committed_at = _parse_dt((commit_obj.get('committer') or {}).get('date'))
    return [
        _build_commit_file_row(org, repo_name, commit, file, committed_at, collected_at)
        for file in (commit.get('files') or [])
    ]


def _commit_has_detail(commit):
    """Return whether a commit payload has detail fields worth preserving."""
    return bool(commit.get('files') or commit.get('stats'))


def _merge_commit_observations(commits):
    """Merge duplicate SHA observations while preserving source memberships."""
    merged = {}
    for commit in commits:
        sha = commit.get('sha')
        if not sha:
            continue
        if sha not in merged:
            merged[sha] = dict(commit)
            merged[sha]['_ledger_sources'] = list(commit.get('_ledger_sources') or [])
            continue
        existing = merged[sha]
        existing['_ledger_sources'].extend(commit.get('_ledger_sources') or [])
        if _commit_has_detail(commit) and not _commit_has_detail(existing):
            replacement = dict(commit)
            replacement['_ledger_sources'] = existing['_ledger_sources']
            merged[sha] = replacement
    return list(merged.values())


def _commit_committed_at(commit):
    """Return parsed commit timestamp from a GitHub commit payload."""
    commit_obj = commit.get('commit') or {}
    return _parse_dt((commit_obj.get('committer') or {}).get('date'))


def _commit_subject_pr_number(commit):
    """Return PR number parsed from a commit subject."""
    subject, _body = _commit_message_parts(commit.get('commit') or {})
    return _extract_pr_number_from_subject(subject)


def _source_row_key(sha, source):
    """Return a stable dedupe key for one commit-source fact."""
    return (
        sha,
        source.get('source_kind'),
        source.get('source_id'),
        source.get('pr_number'),
        source.get('branch'),
    )


def _build_commit_link_rows(org, repo_name, commit, collected_at):
    """Transform commit source memberships into normalized link rows."""
    sha = commit.get('sha')
    committed_at = _commit_committed_at(commit)
    year, month = _timestamp_partition(committed_at or collected_at)
    sources = _commit_sources(commit, fallback_pr_number=_commit_subject_pr_number(commit))
    rows = []
    seen = set()
    for source in sources:
        key = _source_row_key(sha, source)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            'org': org,
            'repo': repo_name,
            'year': year,
            'month': month,
            'collected_at': collected_at,
            'sha': sha,
            'source_kind': source.get('source_kind'),
            'source_id': source.get('source_id'),
            'pr_number': source.get('pr_number'),
            'branch': source.get('branch'),
            'observed_at': committed_at,
            'evidence': source.get('evidence'),
        })
    return rows


def _delivery_mode(parent_count, pr_number):
    """Classify how a default-branch commit landed."""
    if pr_number is not None:
        return 'merge_commit' if parent_count > 1 else 'squash'
    return 'merge_commit' if parent_count > 1 else 'direct_main_candidate'


def _build_delivery_event_row(org, repo_name, commit, collected_at):
    """Build a delivery event row for commits observed on the default branch."""
    sources = _commit_sources(commit, fallback_pr_number=_commit_subject_pr_number(commit))
    if not _on_main(sources):
        return None
    committed_at = _commit_committed_at(commit)
    year, month = _timestamp_partition(committed_at or collected_at)
    parent_count = len(commit.get('parents') or [])
    pr_number = _commit_pr_number(_commit_subject_pr_number(commit), sources)
    evidence = ','.join(sorted({source.get('evidence') for source in sources if source.get('evidence')}))
    return {
        'org': org,
        'repo': repo_name,
        'year': year,
        'month': month,
        'collected_at': collected_at,
        'delivery_sha': commit.get('sha'),
        'delivered_at': committed_at,
        'delivery_mode': _delivery_mode(parent_count, pr_number),
        'pr_number': pr_number,
        'evidence': evidence,
    }


def process_commit_ledger_to_rows(all_commits_data, org):
    """Transform commit observations into canonical, link, and delivery rows."""
    collected_at = pd.Timestamp(datetime.now(timezone.utc))
    commit_rows = []
    file_rows = []
    link_rows = []
    delivery_rows = []

    for repo_name, commits in all_commits_data.items():
        for commit in _merge_commit_observations(commits):
            commit_rows.append(_build_commit_row(org, repo_name, commit, collected_at))
            file_rows.extend(_build_commit_file_rows(org, repo_name, commit, collected_at))
            link_rows.extend(_build_commit_link_rows(org, repo_name, commit, collected_at))
            delivery_row = _build_delivery_event_row(org, repo_name, commit, collected_at)
            if delivery_row:
                delivery_rows.append(delivery_row)

    return commit_rows, file_rows, link_rows, delivery_rows


def process_commits_to_rows(all_commits_data, org):
    """Transform GitHub commit details into commit and commit-file rows."""
    commit_rows, file_rows, _link_rows, _delivery_rows = process_commit_ledger_to_rows(all_commits_data, org)
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
