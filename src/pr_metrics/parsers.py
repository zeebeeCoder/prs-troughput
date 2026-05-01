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


def classify_activity(
    subject: str | None,
    paths: Iterable[str] | None = None,
    conventional_type: str | None = None,
) -> str:
    """Classify commit activity from Conventional Commit type, paths, and keywords."""
    lowered_subject = (subject or "").lower()

    if lowered_subject.startswith("revert") or "revert" in lowered_subject:
        return "revert"

    if conventional_type:
        mapped = CONVENTIONAL_ACTIVITY.get(conventional_type.lower())
        if mapped:
            return mapped

    paths_list = [path for path in (paths or []) if path]
    lowered_paths = [path.lower() for path in paths_list]

    if any(path.startswith(".claude/") or path.startswith(".opencode/") or path.endswith("agents.md") for path in lowered_paths):
        return "agent_tooling"
    if any(is_test_path(path) for path in lowered_paths):
        return "test"
    if lowered_paths and all(path.startswith("docs/") or path.endswith(".md") for path in lowered_paths):
        return "docs"
    if any(path.startswith("infra/") or "terraform" in path or "pulumi" in path for path in lowered_paths):
        return "infra"
    if any(Path(path).name in {"package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "uv.lock", "poetry.lock"} for path in lowered_paths):
        return "dependency"
    if any(keyword in lowered_subject for keyword in SENSITIVE_KEYWORDS) or any(is_sensitive_path(path) for path in lowered_paths):
        return "security_auth"

    return "other"
