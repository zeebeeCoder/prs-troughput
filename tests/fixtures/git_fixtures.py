"""Real git fixture helpers for local-git integration tests."""

from __future__ import annotations

import subprocess
from pathlib import Path


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
    return result.stdout


def init_repo(path: Path, *, branch: str = "main") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", branch, str(path)], check=True, capture_output=True, text=True)
    git(path, "config", "user.name", "Test User")
    git(path, "config", "user.email", "test@example.com")
    return path


def commit_file(repo: Path, message: str, files: dict[str, str], *, date: str = "2026-05-13T12:00:00+00:00") -> str:
    for rel_path, content in files.items():
        file_path = repo / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
    git(repo, "add", ".")
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", message],
        check=True,
        capture_output=True,
        text=True,
        env={
            **__import__("os").environ,
            "GIT_AUTHOR_DATE": date,
            "GIT_COMMITTER_DATE": date,
        },
    )
    return git(repo, "rev-parse", "HEAD").strip()


def make_bare_remote(tmp_path: Path, *, repo_name: str = "remote") -> Path:
    workdir = init_repo(tmp_path / f"{repo_name}-work")
    commit_file(workdir, "feat: add login (#42)", {"src/auth.py": "print('login')\n"})
    commit_file(workdir, "fix: typo", {"README.md": "hello\n"})
    git(workdir, "checkout", "-b", "feature/demo")
    commit_file(workdir, "feat: branch work", {"src/feature.py": "print('feature')\n"})
    git(workdir, "checkout", "main")
    bare = tmp_path / f"{repo_name}.git"
    subprocess.run(["git", "clone", "--bare", str(workdir), str(bare)], check=True, capture_output=True, text=True)
    return bare
