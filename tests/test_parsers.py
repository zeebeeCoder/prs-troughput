from pr_metrics.parsers import (
    classify_activity,
    extract_spec_name,
    extract_task_id,
    is_sensitive_path,
    is_test_path,
    parse_conventional_commit,
)


def test_extract_task_id_from_texts():
    assert extract_task_id("Add print form DEV-3871", "fallback DEV-1") == "DEV-3871"
    assert extract_task_id("no ticket here") is None


def test_extract_spec_name():
    assert extract_spec_name("[spec: checkout ledger] implement flow") == "checkout ledger"
    assert extract_spec_name("nothing") is None


def test_parse_conventional_commit():
    assert parse_conventional_commit("feat(auth): add token refresh") == ("feat", "auth")
    assert parse_conventional_commit("Fix GitHub API timeouts") == (None, None)


def test_classify_activity_prefers_conventional_type():
    assert classify_activity("feat(api): add thing", ["docs/readme.md"], "feat") == "feature_dev"
    assert classify_activity("revert: undo bad deploy", ["src/app.py"], None) == "revert"


def test_classify_activity_from_paths():
    assert classify_activity("update docs", ["README.md", "docs/usage.md"], None) == "docs"
    assert classify_activity("add coverage", ["tests/test_api.py"], None) == "test"
    assert classify_activity("agent config", [".claude/settings.json"], None) == "agent_tooling"
    assert classify_activity("rotate token", ["src/auth/session.py"], None) == "security_auth"


def test_path_helpers():
    assert is_test_path("src/foo/bar.spec.ts")
    assert is_sensitive_path("infra/secrets.tf")
