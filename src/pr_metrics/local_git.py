"""Read-only local git extractors for hybrid ledger mode."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass
class GitCommandStats:
    """Mutable command counter for extraction summaries."""

    commands: int = 0


class StaleRefsError(RuntimeError):
    """Raised when remote-tracking refs are older than the requested window."""


def _run_git(repo: Path, args: list[str], stats: GitCommandStats | None = None) -> str:
    if stats is not None:
        stats.commands += 1
    result = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
    return result.stdout


def is_git_worktree(repo: Path, stats: GitCommandStats | None = None) -> bool:
    """Return whether path is a git worktree/clone."""
    try:
        return _run_git(repo, ["rev-parse", "--is-inside-work-tree"], stats).strip() == "true"
    except subprocess.CalledProcessError:
        return False


def default_branch_ref(repo: Path, remote: str = "origin", stats: GitCommandStats | None = None) -> str:
    """Return refs/remotes/<remote>/<default> with main/master fallbacks."""
    try:
        value = _run_git(repo, ["symbolic-ref", f"refs/remotes/{remote}/HEAD"], stats).strip()
        if value:
            return value
    except subprocess.CalledProcessError:
        pass
    for branch in ("main", "master"):
        ref = f"refs/remotes/{remote}/{branch}"
        try:
            _run_git(repo, ["rev-parse", "--verify", ref], stats)
            return ref
        except subprocess.CalledProcessError:
            continue
    return f"refs/remotes/{remote}/HEAD"


def remote_ref_fresh(repo: Path, days_back: int, remote: str = "origin", stats: GitCommandStats | None = None) -> bool:
    """Return whether any remote-tracking ref was updated within the requested window."""
    output = _run_git(repo, ["for-each-ref", f"refs/remotes/{remote}", "--format=%(committerdate:iso8601-strict)"], stats)
    latest: datetime | None = None
    for line in output.splitlines():
        if not line.strip():
            continue
        stamp = datetime.fromisoformat(line.strip().replace("Z", "+00:00"))
        latest = stamp if latest is None or stamp > latest else latest
    if latest is None:
        return False
    return latest >= datetime.now(timezone.utc) - timedelta(days=days_back)


def ensure_fresh_refs(repo: Path, days_back: int, *, allow_stale: bool = False, remote: str = "origin", stats: GitCommandStats | None = None) -> None:
    """Raise when refs are stale and the caller did not opt out."""
    if allow_stale:
        return
    if not remote_ref_fresh(repo, days_back, remote=remote, stats=stats):
        raise StaleRefsError(
            f"Remote refs under {remote!r} are older than the --days {days_back} window; rerun with --allow-stale to override"
        )


def extract_commits(
    repo: Path,
    *,
    days_back: int,
    remote: str = "origin",
    full_body: bool = False,
    stats: GitCommandStats | None = None,
    telemetry=None,
    org: str | None = None,
    repo_name: str | None = None,
) -> list[dict]:
    """Extract default-branch commits and per-file churn via one git log pass."""
    span_fields = {"org": org, "repo": repo_name, "clone_path": str(repo)}
    if telemetry:
        with telemetry.span("local_git.default_branch_ref", **span_fields):
            default_ref = default_branch_ref(repo, remote=remote, stats=stats)
    else:
        default_ref = default_branch_ref(repo, remote=remote, stats=stats)
    since_iso = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
    log_args = [
        "log",
        default_ref,
        f"--since={since_iso}",
        "--first-parent",
        "--format=%x1e%H%x1f%P%x1f%an%x1f%ae%x1f%aI%x1f%cn%x1f%ce%x1f%cI%x1f%s%x1f%b",
        "--numstat",
    ]
    if telemetry:
        with telemetry.span("local_git.git_log_numstat", **span_fields, default_ref=default_ref):
            output = _run_git(repo, log_args, stats)
    else:
        output = _run_git(repo, log_args, stats)
    body_limit = None if full_body else 8192
    if telemetry:
        with telemetry.span("local_git.parse_commits", **span_fields):
            commits = [_parse_commit_record(record, body_limit=body_limit) for record in output.split("\x1e") if record.strip()]
        telemetry.record("local_git.extract_commits.rows", org=org, repo=repo_name, rows=len(commits), status="ok")
        return commits
    return [_parse_commit_record(record, body_limit=body_limit) for record in output.split("\x1e") if record.strip()]


def extract_branches(
    repo: Path,
    *,
    open_pr_branch_map: dict[str, dict],
    remote: str = "origin",
    stats: GitCommandStats | None = None,
    telemetry=None,
    org: str | None = None,
    repo_name: str | None = None,
) -> list[dict]:
    """Extract branch rows for branches that have open PRs."""
    if not open_pr_branch_map:
        return []
    span_fields = {"org": org, "repo": repo_name, "clone_path": str(repo), "open_pr_branches": len(open_pr_branch_map)}
    if telemetry:
        with telemetry.span("local_git.extract_branches", **span_fields):
            return _extract_branches_impl(repo, open_pr_branch_map=open_pr_branch_map, remote=remote, stats=stats)
    return _extract_branches_impl(repo, open_pr_branch_map=open_pr_branch_map, remote=remote, stats=stats)


def _extract_branches_impl(
    repo: Path,
    *,
    open_pr_branch_map: dict[str, dict],
    remote: str = "origin",
    stats: GitCommandStats | None = None,
) -> list[dict]:
    default_ref = default_branch_ref(repo, remote=remote, stats=stats)
    default_branch = default_ref.rsplit("/", 1)[-1]
    default_head = _run_git(repo, ["rev-parse", default_ref], stats).strip()
    rows: list[dict] = []
    for branch_name, pr in sorted(open_pr_branch_map.items()):
        branch_ref = f"refs/remotes/{remote}/{branch_name}"
        try:
            head_sha = _run_git(repo, ["rev-parse", "--verify", branch_ref], stats).strip()
        except subprocess.CalledProcessError:
            continue
        counts = _run_git(repo, ["rev-list", "--left-right", "--count", f"{default_ref}...{branch_ref}"], stats).split()
        behind = int(counts[0]) if counts else None
        ahead = int(counts[1]) if len(counts) > 1 else None
        latest = _run_git(repo, ["log", "-1", "--format=%aI%x1f%an", branch_ref], stats).strip().split("\x1f", 1)
        rows.append({
            "branch": branch_name,
            "head_sha": head_sha,
            "default_branch": default_branch,
            "default_head_sha": default_head,
            "last_commit_at": latest[0] if latest else None,
            "last_author": latest[1] if len(latest) > 1 else None,
            "ahead_main": ahead,
            "behind_main": behind,
            "has_open_pr": True,
            "pr_number": pr.get("number"),
            "pr_title": pr.get("title"),
            "pr_url": pr.get("url"),
        })
    return rows


def _parse_commit_record(record: str, *, body_limit: int | None) -> dict:
    header_line, *tail_lines = record.lstrip("\n").splitlines()
    fields = header_line.split("\x1f", 9)
    if len(fields) < 10:
        raise ValueError(f"Unexpected git log record: {header_line!r}")
    sha, parents, author_name, author_email, authored_at, committer_name, committer_email, committed_at, subject, first_body = fields
    body_lines = [first_body] if first_body else []
    files: list[dict] = []
    additions = 0
    deletions = 0
    for line in tail_lines:
        parsed = _parse_numstat(line)
        if parsed is None:
            if line.strip():
                body_lines.append(line)
            continue
        file_additions, file_deletions, path = parsed
        additions += file_additions
        deletions += file_deletions
        files.append({
            "filename": path,
            "status": "modified",
            "additions": file_additions,
            "deletions": file_deletions,
        })
    body = "\n".join(body_lines).strip() or None
    if body and body_limit is not None and len(body) > body_limit:
        body = body[:body_limit]
    return {
        "sha": sha,
        "parents": [{"sha": parent} for parent in parents.split() if parent],
        "commit": {
            "author": {"name": author_name, "email": author_email, "date": authored_at},
            "committer": {"name": committer_name, "email": committer_email, "date": committed_at},
            "message": f"{subject}\n\n{body}" if body else subject,
        },
        "stats": {"additions": additions, "deletions": deletions},
        "files": files,
        "_ledger_sources": [{
            "source_kind": "default_branch",
            "source_id": "default",
            "pr_number": _extract_pr_number_from_subject(subject),
            "branch": None,
            "evidence": "local_git_first_parent_log",
        }],
    }


def _parse_numstat(line: str) -> tuple[int, int, str] | None:
    parts = line.split("\t")
    if len(parts) != 3:
        return None
    added, deleted, path = parts
    if not (_is_numstat_count(added) and _is_numstat_count(deleted)):
        return None
    return _numstat_count(added), _numstat_count(deleted), path


def _is_numstat_count(value: str) -> bool:
    return value == "-" or value.isdigit()


def _numstat_count(value: str) -> int:
    return 0 if value == "-" else int(value)


def _extract_pr_number_from_subject(subject: str | None) -> int | None:
    match = re.search(r"\(#(\d+)\)", subject or "")
    return int(match.group(1)) if match else None
