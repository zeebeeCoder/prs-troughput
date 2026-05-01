#!/usr/bin/env python3
"""GitHub API interactions using gh CLI."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote


def run_gh_command(cmd, max_retries=3, initial_delay=2):
    """Run gh CLI command and return JSON result with retry logic

    Args:
        cmd: Command to execute
        max_retries: Maximum number of retry attempts (default: 3)
        initial_delay: Initial delay in seconds before first retry (default: 2)

    Returns:
        JSON parsed result or empty list on failure
    """
    for attempt in range(max_retries):
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=True)
            return json.loads(result.stdout) if result.stdout.strip() else []
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.strip()

            # Check if it's a retryable error (timeout, bad gateway, rate limit)
            is_retryable = any(code in error_msg.lower() for code in ['502', '504', '503', 'timeout', 'rate limit'])

            if is_retryable and attempt < max_retries - 1:
                delay = initial_delay * (2 ** attempt)  # Exponential backoff
                print(f"⚠️  {error_msg} - Retrying in {delay}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(delay)
                continue
            else:
                # Non-retryable error or max retries reached
                print(f"Error: {error_msg}")
                return []
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON response: {e}")
            return []

    return []


def run_gh_api(endpoint, max_retries=3, initial_delay=2):
    """Run `gh api` for an endpoint and return parsed JSON."""
    return run_gh_command(f"gh api {shlex.quote(endpoint)}", max_retries=max_retries, initial_delay=initial_delay)


def get_org_repos(org):
    """Get all active repositories in the org (exclude archived and forks)"""
    cmd = f"gh repo list {shlex.quote(org)} --json name --no-archived --source --limit 100"
    return run_gh_command(cmd)


def get_active_repos_from_search(org, days_back=14):
    """Get repositories that have had PR activity in the specified time period"""
    since_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
    cmd = f'gh search prs --owner {shlex.quote(org)} --created ">={since_date}" --json repository --limit 1000'

    try:
        prs_data = run_gh_command(cmd)
        if not prs_data:
            print("⚠️  No PRs found via search, falling back to full repo scan")
            return get_org_repos(org)

        # Extract unique repository names
        repo_names = set()
        for pr in prs_data:
            if pr.get('repository', {}).get('name'):
                repo_names.add(pr['repository']['name'])

        # Convert to expected format (list of dicts with 'name' key)
        active_repos = [{'name': name} for name in sorted(repo_names)]

        print(f"🎯 Found {len(active_repos)} repositories with recent PR activity")
        return active_repos

    except Exception as e:
        print(f"⚠️  Search failed ({e}), falling back to full repo scan")
        return get_org_repos(org)


def get_repo_prs(org, repo_name, days_back=14):
    """Get PRs for a repository from the last N days

    Args:
        org: GitHub organization name
        repo_name: Repository name
        days_back: Number of days to look back

    Returns:
        List of PR dictionaries filtered by date

    Note:
        Limit reduced to 20 to avoid GitHub GraphQL API complexity limits.
        Can be overridden with GH_PR_LIMIT environment variable.
    """
    since_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')

    # Configurable limit (default: 20 to avoid API timeouts)
    # Use environment variable to override if needed
    limit = int(os.getenv('GH_PR_LIMIT', '20'))

    # Don't use --search as it's unreliable; filter in post-processing instead.
    # Keep this field list schema-oriented and cheap: it intentionally avoids the
    # high-complexity commits/files connections while adding raw lifecycle, branch,
    # review, and CI fields needed by derived reports.
    json_fields = ','.join([
        'number', 'author', 'title', 'body', 'url',
        'createdAt', 'updatedAt', 'mergedAt', 'closedAt', 'state',
        'additions', 'deletions', 'changedFiles', 'isDraft', 'labels',
        'headRefName', 'baseRefName', 'headRefOid',
        'reviewDecision', 'reviews', 'latestReviews', 'reviewRequests',
        'mergedBy', 'comments', 'mergeable', 'mergeStateStatus',
        'statusCheckRollup',
    ])
    cmd = (
        f'gh pr list --repo {shlex.quote(f"{org}/{repo_name}")} --state all '
        f'--json {json_fields} --limit {limit}'
    )
    all_prs = run_gh_command(cmd)

    # Filter PRs by date in post-processing. Include recently updated PRs too so
    # old-but-active review queues do not disappear from the snapshot.
    filtered_prs = []
    for pr in all_prs:
        created_date = (pr.get('createdAt') or '')[:10]
        updated_date = (pr.get('updatedAt') or '')[:10]
        if created_date >= since_date or updated_date >= since_date:
            filtered_prs.append(pr)

    return filtered_prs


def get_default_branch(org, repo_name):
    """Return the repository default branch name."""
    data = run_gh_command(
        f"gh repo view {shlex.quote(f'{org}/{repo_name}')} --json defaultBranchRef"
    )
    return (data.get('defaultBranchRef') or {}).get('name') if isinstance(data, dict) else None


def get_open_pr_branch_map(org, repo_name, limit=100):
    """Return head branch -> open PR metadata for a repository."""
    json_fields = 'number,title,body,url,headRefName,headRefOid'
    cmd = (
        f'gh pr list --repo {shlex.quote(f"{org}/{repo_name}")} --state open '
        f'--json {json_fields} --limit {limit}'
    )
    prs = run_gh_command(cmd)
    branch_map = {}
    for pr in prs:
        branch = pr.get('headRefName')
        if branch:
            branch_map[branch] = pr
    return branch_map


def get_repo_branches(org, repo_name, limit=100):
    """Collect remote branch snapshot facts for a repository using gh API."""
    default_branch = get_default_branch(org, repo_name)
    if not default_branch:
        print(f"⚠️  Could not resolve default branch for {org}/{repo_name}")
        return []

    open_prs = get_open_pr_branch_map(org, repo_name)
    encoded_default = quote(default_branch, safe='')
    default_detail = run_gh_api(f"repos/{org}/{repo_name}/branches/{encoded_default}")
    default_head_sha = ((default_detail.get('commit') or {}).get('sha')) if isinstance(default_detail, dict) else None
    branches = run_gh_api(f"repos/{org}/{repo_name}/branches?per_page={min(limit, 100)}")
    rows = []

    for branch in branches[:limit]:
        name = branch.get('name')
        sha = ((branch.get('commit') or {}).get('sha'))
        if not name or not sha:
            continue

        encoded_branch = quote(name, safe='')
        branch_detail = run_gh_api(f"repos/{org}/{repo_name}/branches/{encoded_branch}")
        compare = run_gh_api(f"repos/{org}/{repo_name}/compare/{encoded_default}...{encoded_branch}")

        commit = ((branch_detail.get('commit') or {}).get('commit') or {}) if isinstance(branch_detail, dict) else {}
        author = commit.get('author') or {}
        pr = open_prs.get(name)

        rows.append({
            'branch': name,
            'head_sha': sha,
            'default_branch': default_branch,
            'default_head_sha': default_head_sha,
            'last_commit_at': author.get('date'),
            'last_author': author.get('name'),
            'ahead_main': compare.get('ahead_by') if isinstance(compare, dict) else None,
            'behind_main': compare.get('behind_by') if isinstance(compare, dict) else None,
            'has_open_pr': pr is not None,
            'pr_number': pr.get('number') if pr else None,
            'pr_title': pr.get('title') if pr else None,
            'pr_url': pr.get('url') if pr else None,
        })

    return rows


def get_repo_commits(org, repo_name, days_back=14, limit=100, include_files=True):
    """Collect default-branch commits for a repository via gh API.

    The list endpoint is intentionally scoped to the default branch. This makes
    `on_main` true for collected rows and gives a cheap direct-main lane without
    requiring local clones for every repo.
    """
    since_iso = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat().replace('+00:00', 'Z')
    commits = run_gh_api(
        f"repos/{org}/{repo_name}/commits?since={quote(since_iso, safe=':TZ-')}&per_page={min(limit, 100)}"
    )

    detailed_commits = []
    for commit in commits[:limit]:
        sha = commit.get('sha')
        if not sha:
            continue
        if include_files:
            detail = run_gh_api(f"repos/{org}/{repo_name}/commits/{sha}")
            detailed_commits.append(detail if isinstance(detail, dict) else commit)
        else:
            detailed_commits.append(commit)

    return detailed_commits
