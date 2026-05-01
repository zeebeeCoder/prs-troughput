#!/usr/bin/env python3
"""Deterministic parsers and classifiers for delivery ledger facts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable


TASK_ID_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")
SPEC_RE = re.compile(r"\[spec:\s*([^\]]+)\]", re.IGNORECASE)
CONVENTIONAL_RE = re.compile(
    r"^(?P<type>[a-zA-Z]+)(?:\((?P<scope>[^)]+)\))?(?P<breaking>!)?:\s+(?P<desc>.+)$"
)

CONVENTIONAL_ACTIVITY = {
    "feat": "feature_dev",
    "fix": "bug_fix",
    "refactor": "refactor",
    "docs": "docs",
    "test": "test",
    "chore": "maintenance",
    "ci": "ci",
    "build": "build_dependency",
    "perf": "performance",
    "revert": "revert",
}

SENSITIVE_KEYWORDS = ("auth", "jwt", "token", "permission", "secret", "password", "oauth")
DEPENDENCY_FILES = {"package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "uv.lock", "poetry.lock"}


def extract_task_id(*texts: str | None) -> str | None:
    """Return the first DEV-123 style task id found in the provided text."""
    for text in texts:
        if not text:
            continue
        match = TASK_ID_RE.search(text)
        if match:
            return match.group(1)
    return None


def extract_spec_name(*texts: str | None) -> str | None:
    """Return the first `[spec: name]` marker found in the provided text."""
    for text in texts:
        if not text:
            continue
        match = SPEC_RE.search(text)
        if match:
            return match.group(1).strip()
    return None


def parse_conventional_commit(subject: str | None) -> tuple[str | None, str | None]:
    """Parse a Conventional Commit subject into (type, scope)."""
    if not subject:
        return None, None

    match = CONVENTIONAL_RE.match(subject.strip())
    if not match:
        return None, None

    return match.group("type").lower(), match.group("scope")


def top_level_dir(path: str | None) -> str | None:
    """Return the first path component, or the filename for root-level files."""
    if not path:
        return None
    return path.split("/", 1)[0]


def file_extension(path: str | None) -> str | None:
    """Return the lowercase file extension without the leading dot."""
    if not path:
        return None
    suffix = Path(path).suffix.lower()
    return suffix[1:] if suffix else None


def is_test_path(path: str | None) -> bool:
    """Heuristic test/spec path classifier."""
    if not path:
        return False
    lowered = path.lower()
    name = Path(lowered).name
    return (
        "/test" in lowered
        or "/tests" in lowered
        or lowered.startswith("test/")
        or lowered.startswith("tests/")
        or "/spec" in lowered
        or ".test." in name
        or ".spec." in name
        or name.startswith("test_")
    )


def is_generated_path(path: str | None) -> bool:
    """Heuristic generated/vendor path classifier."""
    if not path:
        return False
    lowered = path.lower()
    return any(
        marker in lowered
        for marker in (
            "generated",
            "vendor/",
            "node_modules/",
            "dist/",
            "build/",
            "coverage/",
            "package-lock.json",
            "yarn.lock",
            "uv.lock",
            "poetry.lock",
        )
    )


def is_sensitive_path(path: str | None) -> bool:
    """Heuristic sensitive/security path classifier."""
    if not path:
        return False
    lowered = path.lower()
    return any(keyword in lowered for keyword in SENSITIVE_KEYWORDS)


def _normalise_paths(paths: Iterable[str] | None) -> list[str]:
    """Return lowercase non-empty paths for activity classification."""
    return [path.lower() for path in (paths or []) if path]


def _has_agent_tooling_path(paths: list[str]) -> bool:
    return any(path.startswith(".claude/") or path.startswith(".opencode/") or path.endswith("agents.md") for path in paths)


def _all_docs_paths(paths: list[str]) -> bool:
    return bool(paths) and all(path.startswith("docs/") or path.endswith(".md") for path in paths)


def _has_infra_path(paths: list[str]) -> bool:
    return any(path.startswith("infra/") or "terraform" in path or "pulumi" in path for path in paths)


def _has_dependency_path(paths: list[str]) -> bool:
    return any(Path(path).name in DEPENDENCY_FILES for path in paths)


def _has_security_signal(subject: str, paths: list[str]) -> bool:
    return any(keyword in subject for keyword in SENSITIVE_KEYWORDS) or any(is_sensitive_path(path) for path in paths)


PATH_ACTIVITY_RULES = (
    ("agent_tooling", _has_agent_tooling_path),
    ("test", lambda paths: any(is_test_path(path) for path in paths)),
    ("docs", _all_docs_paths),
    ("infra", _has_infra_path),
    ("dependency", _has_dependency_path),
)


def classify_activity(
    subject: str | None,
    paths: Iterable[str] | None = None,
    conventional_type: str | None = None,
) -> str:
    """Classify commit activity from Conventional Commit type, paths, and keywords."""
    lowered_subject = (subject or "").lower()
    if lowered_subject.startswith("revert") or "revert" in lowered_subject:
        return "revert"

    mapped = CONVENTIONAL_ACTIVITY.get((conventional_type or "").lower())
    if mapped:
        return mapped

    lowered_paths = _normalise_paths(paths)
    for activity, predicate in PATH_ACTIVITY_RULES:
        if predicate(lowered_paths):
            return activity

    if _has_security_signal(lowered_subject, lowered_paths):
        return "security_auth"

    return "other"
