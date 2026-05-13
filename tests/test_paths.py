from pathlib import Path

from pr_metrics.paths import resolve_cache_dir, resolve_data_lake_dir


def test_data_lake_prefers_explicit(monkeypatch, tmp_path):
    monkeypatch.setenv("PR_METRICS_OUTPUT_DIR", str(tmp_path / "env"))

    assert resolve_data_lake_dir(tmp_path / "explicit") == tmp_path / "explicit"


def test_data_lake_uses_env(monkeypatch, tmp_path):
    monkeypatch.setenv("PR_METRICS_OUTPUT_DIR", str(tmp_path / "lake"))

    assert resolve_data_lake_dir() == tmp_path / "lake"


def test_data_lake_uses_xdg_default(monkeypatch, tmp_path):
    monkeypatch.delenv("PR_METRICS_OUTPUT_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    assert resolve_data_lake_dir() == tmp_path / "data" / "pr-metrics" / "lake"


def test_cache_uses_xdg_default(monkeypatch, tmp_path):
    monkeypatch.delenv("PR_METRICS_CACHE_DIR", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    assert resolve_cache_dir() == tmp_path / "cache" / "pr-metrics" / "clones"


def test_cache_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("PR_METRICS_CACHE_DIR", str(tmp_path / "clones"))

    assert resolve_cache_dir() == tmp_path / "clones"
