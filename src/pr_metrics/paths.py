"""Path resolution for pr-metrics data and cache locations."""

from __future__ import annotations

import os
from pathlib import Path


APP_NAME = "pr-metrics"


def _expand(path: str | os.PathLike[str]) -> Path:
    """Return an expanded user path without requiring it to exist."""
    return Path(path).expanduser()


def resolve_data_lake_dir(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the parquet/DuckDB data lake root.

    Precedence:
    1. explicit CLI value
    2. PR_METRICS_OUTPUT_DIR
    3. ${XDG_DATA_HOME:-~/.local/share}/pr-metrics/lake
    """
    if explicit:
        return _expand(explicit)
    env_value = os.getenv("PR_METRICS_OUTPUT_DIR")
    if env_value:
        return _expand(env_value)
    data_home = _expand(os.getenv("XDG_DATA_HOME") or "~/.local/share")
    return data_home / APP_NAME / "lake"


def resolve_cache_dir(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the tool-owned clone cache root.

    Precedence:
    1. explicit CLI value
    2. PR_METRICS_CACHE_DIR
    3. ${XDG_CACHE_HOME:-~/.cache}/pr-metrics/clones
    """
    if explicit:
        return _expand(explicit)
    env_value = os.getenv("PR_METRICS_CACHE_DIR")
    if env_value:
        return _expand(env_value)
    cache_home = _expand(os.getenv("XDG_CACHE_HOME") or "~/.cache")
    return cache_home / APP_NAME / "clones"
