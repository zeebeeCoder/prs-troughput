#!/usr/bin/env python3
"""GitHub API interactions using gh CLI."""

import subprocess
import json
import os
import time
from datetime import datetime, timedelta


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
            is_retryable = any(code in error_msg for code in ['502', '504', '503', 'timeout', 'rate limit'])

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


def get_org_repos(org):
    """Get all active repositories in the org (exclude archived and forks)"""
    cmd = f"gh repo list {org} --json name --no-archived --source --limit 100"
    return run_gh_command(cmd)


def get_active_repos_from_search(org, days_back=14):
    """Get repositories that have had PR activity in the specified time period"""
    since_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
    cmd = f'gh search prs --owner {org} --created ">={since_date}" --json repository --limit 1000'

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

    # Don't use --search as it's unreliable; filter in post-processing instead
    # Enhanced fields: reviews, reviewRequests, mergedBy, comments, changedFiles
    # Note: commits field excluded due to GitHub GraphQL complexity limits (authors connection)
    # We'll calculate commit count from GitHub's commits API if needed later
    cmd = f'gh pr list --repo {org}/{repo_name} --state all --json number,author,title,createdAt,mergedAt,closedAt,state,additions,deletions,isDraft,labels,reviewDecision,reviews,reviewRequests,mergedBy,comments,changedFiles --limit {limit}'
    all_prs = run_gh_command(cmd)

    # Filter PRs by date in post-processing
    filtered_prs = []
    for pr in all_prs:
        if pr.get('createdAt'):
            pr_date = pr['createdAt'][:10]  # Get YYYY-MM-DD part
            if pr_date >= since_date:
                filtered_prs.append(pr)

    return filtered_prs
