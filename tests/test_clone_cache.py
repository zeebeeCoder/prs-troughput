from datetime import timedelta

import pytest

from pr_metrics.clone_cache import CloneCache, CloneLockError
from tests.fixtures.git_fixtures import make_bare_remote


def test_clone_cache_clones_blobless_no_checkout_and_fetches_existing(tmp_path):
    remote = make_bare_remote(tmp_path)
    cache = CloneCache(tmp_path / "cache")

    clone = cache.ensure_clone("Acme", "backend", remote_url=f"file://{remote}")

    assert (clone / ".git").exists()
    assert cache.cloned_count == 1
    assert cache.fetched_count == 0
    assert (clone / ".pr-metrics.access").exists()

    same = cache.ensure_clone("Acme", "backend", remote_url=f"file://{remote}")

    assert same == clone
    assert cache.fetched_count == 0  # no double-fetch within one CloneCache instance

    second_run = CloneCache(tmp_path / "cache")
    second_run.ensure_clone("Acme", "backend", remote_url=f"file://{remote}")
    assert second_run.fetched_count == 1


def test_clone_cache_lists_du_and_clears(tmp_path):
    remote = make_bare_remote(tmp_path)
    cache = CloneCache(tmp_path / "cache")
    cache.ensure_clone("Acme", "backend", remote_url=f"file://{remote}")

    clones = cache.iter_cached_clones()

    assert len(clones) == 1
    assert clones[0].org == "Acme"
    assert clones[0].repo == "backend"
    assert cache.du() > 0

    removed = cache.clear(org="Acme")

    assert len(removed) == 1
    assert not (tmp_path / "cache" / "Acme" / "backend").exists()


def test_clone_cache_prunes_by_access_age(tmp_path):
    remote = make_bare_remote(tmp_path)
    cache = CloneCache(tmp_path / "cache")
    clone = cache.ensure_clone("Acme", "backend", remote_url=f"file://{remote}")
    (clone / ".pr-metrics.access").write_text("2000-01-01T00:00:00+00:00")

    removed = cache.prune(timedelta(days=1))

    assert removed == [clone]
    assert not clone.exists()


def test_clone_cache_lock_contention_times_out(tmp_path):
    cache = CloneCache(tmp_path / "cache", lock_timeout=0.01)
    clone = cache.clone_path("Acme", "backend")
    clone.mkdir(parents=True)
    (clone / ".pr-metrics.lock").write_text("locked")

    with pytest.raises(CloneLockError):
        cache.ensure_clone("Acme", "backend", remote_url="file:///does/not/matter")
