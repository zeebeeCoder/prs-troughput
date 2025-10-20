#!/usr/bin/env python3
"""GitHub API interactions using gh CLI."""

import subprocess
import json
from datetime import datetime, timedelta


def run_gh_command(cmd):
    """Run gh CLI command and return JSON result"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=True)
        return json.loads(result.stdout) if result.stdout.strip() else []
    except subprocess.CalledProcessError as e:
        print(f"Error: {e.stderr}")
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
    """Get PRs for a repository from the last N days"""
    since_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
    # Don't use --search as it's unreliable; filter in post-processing instead
    cmd = f'gh pr list --repo {org}/{repo_name} --state all --json number,author,title,createdAt,mergedAt,closedAt,reviewDecision,additions,deletions,isDraft,labels --limit 200'
    all_prs = run_gh_command(cmd)

    # Filter PRs by date in post-processing
    filtered_prs = []
    for pr in all_prs:
        if pr.get('createdAt'):
            pr_date = pr['createdAt'][:10]  # Get YYYY-MM-DD part
            if pr_date >= since_date:
                filtered_prs.append(pr)

    return filtered_prs
