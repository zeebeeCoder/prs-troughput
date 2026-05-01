"""Read-only local Git validation for collected delivery-lake facts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess

import pandas as pd

from .insights import create_delivery_lake_views


@dataclass(frozen=True)
class ValidationResult:
    """Summary tables from a local Git validation run."""

    commit_summary: pd.DataFrame
    commit_mismatches: pd.DataFrame
    branch_summary: pd.DataFrame
    branch_mismatches: pd.DataFrame


def _git(repo_path: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a read-only git command in a local repo."""
    return subprocess.run(
        ["git", "-C", str(repo_path), *args],
        capture_output=True,
        text=True,
        check=check,
    )


def _git_stdout(repo_path: Path, *args: str) -> str:
    return _git(repo_path, *args).stdout.strip()


def _commit_exists(repo_path: Path, sha: str) -> bool:
    return _git(repo_path, "cat-file", "-e", f"{sha}^{{commit}}", check=False).returncode == 0


def _commit_numstat(repo_path: Path, sha: str) -> tuple[int, int, int]:
    output = _git_stdout(repo_path, "show", "--numstat", "--format=", sha)
    additions = deletions = files = 0
    for line in output.splitlines():
        if not line.strip():
            continue
        added, deleted, *_ = line.split("\t")
        files += 1
        if added != "-":
            additions += int(added)
        if deleted != "-":
            deletions += int(deleted)
    return additions, deletions, files


def _commit_parent_count(repo_path: Path, sha: str) -> int:
    return len(_git_stdout(repo_path, "rev-list", "--parents", "-n", "1", sha).split()) - 1


def _commit_subject(repo_path: Path, sha: str) -> str:
    return _git_stdout(repo_path, "show", "-s", "--format=%s", sha)


def _remote_ref_exists(repo_path: Path, branch: str, remote: str) -> bool:
    return _git(repo_path, "rev-parse", "--verify", "--quiet", f"refs/remotes/{remote}/{branch}", check=False).returncode == 0


def _remote_ref_sha(repo_path: Path, branch: str, remote: str) -> str:
    return _git_stdout(repo_path, "rev-parse", f"refs/remotes/{remote}/{branch}")


def _ahead_behind(repo_path: Path, base_sha: str, branch: str, remote: str) -> tuple[int, int]:
    output = _git_stdout(
        repo_path,
        "rev-list",
        "--left-right",
        "--count",
        f"{base_sha}...refs/remotes/{remote}/{branch}",
    )
    behind, ahead = [int(part) for part in output.split()]
    return ahead, behind


def _empty_result() -> ValidationResult:
    return ValidationResult(
        commit_summary=pd.DataFrame(),
        commit_mismatches=pd.DataFrame(),
        branch_summary=pd.DataFrame(),
        branch_mismatches=pd.DataFrame(),
    )


def validate_local_repo(
    local_repo: str,
    org: str,
    repo: str,
    output_dir: str = "output",
    days_back: int | None = None,
    remote: str = "origin",
) -> ValidationResult:
    """Compare collected GitHub API facts with a local clone without mutating it.

    The validator intentionally does not fetch, checkout, reset, or write files in
    the target repository. Branch checks use local remote-tracking refs as-is, so
    stale local refs are reported as validation drift rather than corrected.
    """
    repo_path = Path(local_repo).expanduser().resolve()
    if not (repo_path / ".git").exists():
        raise ValueError(f"Local path is not a Git repository: {repo_path}")

    con, available = create_delivery_lake_views(output_dir=output_dir, org=org, repo=repo, days_back=days_back)
    try:
        commit_summary, commit_mismatches = _validate_commits(con, available, repo_path)
        branch_summary, branch_mismatches = _validate_branches(con, available, repo_path, remote)
    finally:
        con.close()

    return ValidationResult(commit_summary, commit_mismatches, branch_summary, branch_mismatches)


def _validate_commits(
    con,
    available: set[str],
    repo_path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if "commits_latest" not in available:
        return pd.DataFrame([{"dataset": "commits", "status": "missing_parquet"}]), pd.DataFrame()

    commits = con.execute("""
        SELECT sha, parent_count, additions, deletions, changed_files, subject
        FROM commits_latest
        ORDER BY committed_at DESC NULLS LAST
    """).fetchdf()

    issues = []
    present = 0
    exact = 0
    field_mismatch_count = 0
    for row in commits.to_dict("records"):
        sha = row["sha"]
        if not sha or not _commit_exists(repo_path, sha):
            issues.append({"kind": "commit_missing_locally", "sha": sha, "field": "sha"})
            continue

        present += 1
        local_parent_count = _commit_parent_count(repo_path, sha)
        local_additions, local_deletions, local_files = _commit_numstat(repo_path, sha)
        local_subject = _commit_subject(repo_path, sha)
        row_exact = True

        comparisons = {
            "parent_count": (local_parent_count, row.get("parent_count")),
            "additions": (local_additions, row.get("additions")),
            "deletions": (local_deletions, row.get("deletions")),
            "changed_files": (local_files, row.get("changed_files")),
            "subject": (local_subject, row.get("subject")),
        }
        for field, (local_value, parquet_value) in comparisons.items():
            if pd.isna(parquet_value):
                parquet_value = None
            if local_value != parquet_value:
                row_exact = False
                field_mismatch_count += 1
                issues.append({
                    "kind": "commit_field_mismatch",
                    "sha": sha[:8],
                    "field": field,
                    "local": local_value,
                    "parquet": parquet_value,
                })

        if row_exact:
            exact += 1

    total = len(commits)
    summary = pd.DataFrame([{
        "dataset": "commits",
        "parquet_rows": total,
        "present_locally": present,
        "comparable_rows": present,
        "exact_rows": exact,
        "missing_locally": total - present,
        "field_mismatch_count": field_mismatch_count,
        "issue_count": len(issues),
        "accuracy_pct": round(100.0 * exact / present, 1) if present else None,
    }])
    return summary, pd.DataFrame(issues)


def _validate_branches(
    con,
    available: set[str],
    repo_path: Path,
    remote: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if "branches_latest" not in available:
        return pd.DataFrame([{"dataset": "branches", "status": "missing_parquet"}]), pd.DataFrame()

    columns = set(con.execute("DESCRIBE branches_latest").fetchdf()["column_name"])
    default_branch_expr = "default_branch" if "default_branch" in columns else "NULL::VARCHAR AS default_branch"
    default_head_expr = "default_head_sha" if "default_head_sha" in columns else "NULL::VARCHAR AS default_head_sha"
    branches = con.execute(f"""
        SELECT branch, head_sha, ahead_main, behind_main, {default_branch_expr}, {default_head_expr}
        FROM branches_latest
        ORDER BY branch
    """).fetchdf()

    issues = []
    present = 0
    comparable = 0
    exact = 0
    field_mismatch_count = 0
    for row in branches.to_dict("records"):
        branch = row["branch"]
        if not branch or not _remote_ref_exists(repo_path, branch, remote):
            issues.append({"kind": "branch_ref_missing_locally", "branch": branch, "field": "ref"})
            continue

        present += 1
        local_head = _remote_ref_sha(repo_path, branch, remote)
        base_sha = row.get("default_head_sha")
        row_exact = True
        head_matches = local_head == row.get("head_sha")

        if not base_sha:
            default_branch = row.get("default_branch")
            if default_branch and _remote_ref_exists(repo_path, default_branch, remote):
                base_sha = _remote_ref_sha(repo_path, default_branch, remote)

        if base_sha and _commit_exists(repo_path, base_sha):
            comparable += 1
            if not head_matches:
                row_exact = False
                field_mismatch_count += 1
                issues.append({
                    "kind": "branch_field_mismatch",
                    "branch": branch,
                    "field": "head_sha",
                    "local": local_head[:8],
                    "parquet": (row.get("head_sha") or "")[:8],
                })

            local_ahead, local_behind = _ahead_behind(repo_path, base_sha, branch, remote)
            for field, local_value in (("ahead_main", local_ahead), ("behind_main", local_behind)):
                parquet_value = row.get(field)
                if pd.isna(parquet_value):
                    parquet_value = None
                if local_value != parquet_value:
                    row_exact = False
                    field_mismatch_count += 1
                    issues.append({
                        "kind": "branch_field_mismatch",
                        "branch": branch,
                        "field": field,
                        "local": local_value,
                        "parquet": parquet_value,
                    })

            if row_exact:
                exact += 1
        else:
            issue_kind = "default_head_missing_locally"
            if not head_matches:
                issue_kind = "local_ref_differs_and_default_head_missing"
            issues.append({
                "kind": issue_kind,
                "branch": branch,
                "field": "default_head_sha",
                "local": None,
                "parquet": (base_sha or "")[:8],
            })

    total = len(branches)
    summary = pd.DataFrame([{
        "dataset": "branches",
        "parquet_rows": total,
        "present_locally": present,
        "comparable_rows": comparable,
        "exact_rows": exact,
        "missing_locally": total - present,
        "field_mismatch_count": field_mismatch_count,
        "issue_count": len(issues),
        "accuracy_pct": round(100.0 * exact / comparable, 1) if comparable else None,
    }])
    return summary, pd.DataFrame(issues)
