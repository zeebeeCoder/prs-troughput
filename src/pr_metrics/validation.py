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



def _missing_dataset_result(dataset: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return the standard result when a parquet dataset is unavailable."""
    return pd.DataFrame([{"dataset": dataset, "status": "missing_parquet"}]), pd.DataFrame()


def _clean_parquet_value(value):
    """Normalize pandas missing scalars before comparing with local Git values."""
    return None if pd.isna(value) else value


def _validation_summary(dataset, total, present, comparable, exact, field_mismatch_count, issue_count):
    """Build the standard validation summary DataFrame."""
    denominator = comparable if dataset == "branches" else present
    return pd.DataFrame([{
        "dataset": dataset,
        "parquet_rows": total,
        "present_locally": present,
        "comparable_rows": comparable,
        "exact_rows": exact,
        "missing_locally": total - present,
        "field_mismatch_count": field_mismatch_count,
        "issue_count": issue_count,
        "accuracy_pct": round(100.0 * exact / denominator, 1) if denominator else None,
    }])


def _commit_comparisons(repo_path: Path, row) -> dict[str, tuple[object, object]]:
    """Return local-vs-parquet field comparisons for a commit row."""
    sha = row["sha"]
    additions, deletions, files = _commit_numstat(repo_path, sha)
    return {
        "parent_count": (_commit_parent_count(repo_path, sha), row.get("parent_count")),
        "additions": (additions, row.get("additions")),
        "deletions": (deletions, row.get("deletions")),
        "changed_files": (files, row.get("changed_files")),
        "subject": (_commit_subject(repo_path, sha), row.get("subject")),
    }


def _commit_field_issues(repo_path: Path, row) -> list[dict[str, object]]:
    """Return field mismatch issues for one locally present commit."""
    issues = []
    sha = row["sha"]
    for field, (local_value, parquet_value) in _commit_comparisons(repo_path, row).items():
        parquet_value = _clean_parquet_value(parquet_value)
        if local_value != parquet_value:
            issues.append({
                "kind": "commit_field_mismatch",
                "sha": sha[:8],
                "field": field,
                "local": local_value,
                "parquet": parquet_value,
            })
    return issues


def _validate_commit_row(repo_path: Path, row) -> tuple[bool, bool, list[dict[str, object]]]:
    """Validate one commit row. Returns (present_locally, exact, issues)."""
    sha = row["sha"]
    if not sha or not _commit_exists(repo_path, sha):
        return False, False, [{"kind": "commit_missing_locally", "sha": sha, "field": "sha"}]

    issues = _commit_field_issues(repo_path, row)
    return True, not issues, issues


def _validate_commits(
    con,
    available: set[str],
    repo_path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if "commits_latest" not in available:
        return _missing_dataset_result("commits")

    commits = con.execute("""
        SELECT sha, parent_count, additions, deletions, changed_files, subject
        FROM commits_latest
        ORDER BY committed_at DESC NULLS LAST
    """).fetchdf()

    issues = []
    present = exact = field_mismatch_count = 0
    for row in commits.to_dict("records"):
        row_present, row_exact, row_issues = _validate_commit_row(repo_path, row)
        present += int(row_present)
        exact += int(row_exact)
        field_mismatch_count += sum(1 for issue in row_issues if issue["kind"] == "commit_field_mismatch")
        issues.extend(row_issues)

    summary = _validation_summary("commits", len(commits), present, present, exact, field_mismatch_count, len(issues))
    return summary, pd.DataFrame(issues)


def _branch_rows(con) -> pd.DataFrame:
    """Load branch validation rows while tolerating older schemas."""
    columns = set(con.execute("DESCRIBE branches_latest").fetchdf()["column_name"])
    default_branch_expr = "default_branch" if "default_branch" in columns else "NULL::VARCHAR AS default_branch"
    default_head_expr = "default_head_sha" if "default_head_sha" in columns else "NULL::VARCHAR AS default_head_sha"
    return con.execute(f"""
        SELECT branch, head_sha, ahead_main, behind_main, {default_branch_expr}, {default_head_expr}
        FROM branches_latest
        ORDER BY branch
    """).fetchdf()


def _resolve_base_sha(repo_path: Path, row, remote: str):
    """Resolve the default branch base SHA for ahead/behind comparison."""
    base_sha = row.get("default_head_sha")
    default_branch = row.get("default_branch")
    if not base_sha and default_branch and _remote_ref_exists(repo_path, default_branch, remote):
        return _remote_ref_sha(repo_path, default_branch, remote)
    return base_sha


def _branch_field_issue(branch, field, local_value, parquet_value):
    """Build a branch field mismatch issue."""
    return {
        "kind": "branch_field_mismatch",
        "branch": branch,
        "field": field,
        "local": local_value,
        "parquet": parquet_value,
    }


def _branch_head_issue(row, local_head):
    """Return a head SHA mismatch issue."""
    return _branch_field_issue(row["branch"], "head_sha", local_head[:8], (row.get("head_sha") or "")[:8])


def _branch_ahead_behind_issues(repo_path: Path, row, base_sha: str, remote: str) -> list[dict[str, object]]:
    """Return ahead/behind mismatch issues for a comparable branch."""
    local_ahead, local_behind = _ahead_behind(repo_path, base_sha, row["branch"], remote)
    issues = []
    for field, local_value in (("ahead_main", local_ahead), ("behind_main", local_behind)):
        parquet_value = _clean_parquet_value(row.get(field))
        if local_value != parquet_value:
            issues.append(_branch_field_issue(row["branch"], field, local_value, parquet_value))
    return issues


def _missing_default_head_issue(row, base_sha, head_matches):
    """Return issue for a branch whose default base cannot be compared locally."""
    issue_kind = "default_head_missing_locally" if head_matches else "local_ref_differs_and_default_head_missing"
    return {
        "kind": issue_kind,
        "branch": row["branch"],
        "field": "default_head_sha",
        "local": None,
        "parquet": (base_sha or "")[:8],
    }


def _validate_branch_row(repo_path: Path, row, remote: str) -> dict[str, object]:
    """Validate one branch row and return stats plus issues."""
    branch = row["branch"]
    if not branch or not _remote_ref_exists(repo_path, branch, remote):
        return {"present": False, "comparable": False, "exact": False, "issues": [{"kind": "branch_ref_missing_locally", "branch": branch, "field": "ref"}]}

    local_head = _remote_ref_sha(repo_path, branch, remote)
    base_sha = _resolve_base_sha(repo_path, row, remote)
    head_matches = local_head == row.get("head_sha")
    if not (base_sha and _commit_exists(repo_path, base_sha)):
        return {"present": True, "comparable": False, "exact": False, "issues": [_missing_default_head_issue(row, base_sha, head_matches)]}

    issues = [] if head_matches else [_branch_head_issue(row, local_head)]
    issues.extend(_branch_ahead_behind_issues(repo_path, row, base_sha, remote))
    return {"present": True, "comparable": True, "exact": not issues, "issues": issues}


def _validate_branches(
    con,
    available: set[str],
    repo_path: Path,
    remote: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if "branches_latest" not in available:
        return _missing_dataset_result("branches")

    branches = _branch_rows(con)
    issues = []
    present = comparable = exact = field_mismatch_count = 0
    for row in branches.to_dict("records"):
        result = _validate_branch_row(repo_path, row, remote)
        present += int(result["present"])
        comparable += int(result["comparable"])
        exact += int(result["exact"])
        row_issues = result["issues"]
        field_mismatch_count += sum(1 for issue in row_issues if issue["kind"] == "branch_field_mismatch")
        issues.extend(row_issues)

    summary = _validation_summary("branches", len(branches), present, comparable, exact, field_mismatch_count, len(issues))
    return summary, pd.DataFrame(issues)
