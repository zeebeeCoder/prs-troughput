"""Test-suite guardrails."""

from __future__ import annotations

import shlex
import subprocess

import pytest


@pytest.fixture(autouse=True)
def fail_real_gh_subprocess(monkeypatch):
    """Fail tests that accidentally invoke the real gh CLI.

    Git subprocesses remain allowed so local-git fixtures exercise real plumbing.
    Tests that intentionally unit-test gh wrappers monkeypatch subprocess.run with
    canned responses, replacing this guard in that scope.
    """
    real_run = subprocess.run

    def guarded_run(cmd, *args, **kwargs):
        first = None
        if isinstance(cmd, str):
            try:
                parts = shlex.split(cmd)
            except ValueError:
                parts = cmd.split()
            first = parts[0] if parts else None
        elif isinstance(cmd, (list, tuple)) and cmd:
            first = str(cmd[0])
        if first == "gh":
            raise AssertionError(f"tests must not invoke real gh subprocess: {cmd!r}")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", guarded_run)
