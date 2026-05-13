import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "skills" / "delivery-insights" / "scripts" / "temporal_heatmap.py"


def load_script_module():
    spec = importlib.util.spec_from_file_location("temporal_heatmap", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sample_activity():
    return pd.DataFrame([
        {
            "unit_kind": "commit",
            "actor": "alice",
            "category": "feature_development",
            "repo": "backend",
            "activity_date": "2026-05-04",
            "week_start": "2026-05-04",
            "month_start": "2026-05-01",
            "weekday_label": "Mon",
            "hour_of_day": 9,
            "units": 1,
            "churn": 10,
            "changed_files": 2,
            "strategic_units": 1,
            "operational_units": 0,
            "risk_score": 3,
        },
        {
            "unit_kind": "commit",
            "actor": "alice",
            "category": "bug_fix",
            "repo": "backend",
            "activity_date": "2026-05-05",
            "week_start": "2026-05-04",
            "month_start": "2026-05-01",
            "weekday_label": "Tue",
            "hour_of_day": 10,
            "units": 1,
            "churn": 20,
            "changed_files": 3,
            "strategic_units": 1,
            "operational_units": 0,
            "risk_score": 1,
        },
        {
            "unit_kind": "commit",
            "actor": "bob",
            "category": "docs",
            "repo": "frontend",
            "activity_date": "2026-05-05",
            "week_start": "2026-05-04",
            "month_start": "2026-05-01",
            "weekday_label": "Tue",
            "hour_of_day": 9,
            "units": 1,
            "churn": 5,
            "changed_files": 1,
            "strategic_units": 1,
            "operational_units": 0,
            "risk_score": 0,
        },
        {
            "unit_kind": "commit",
            "actor": "bot:github-actions",
            "category": "maintenance",
            "repo": "backend",
            "activity_date": "2026-05-06",
            "week_start": "2026-05-04",
            "month_start": "2026-05-01",
            "weekday_label": "Wed",
            "hour_of_day": 3,
            "units": 1,
            "churn": 100,
            "changed_files": 1,
            "strategic_units": 0,
            "operational_units": 1,
            "risk_score": 0,
        },
    ])


def args(**overrides):
    base = {
        "unit": "commit",
        "include_bots": False,
        "actors": None,
        "categories": None,
        "row": "actor",
        "col": "date",
        "metric": "count",
        "top_n_rows": 12,
        "normalize": "none",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_apply_preset_sets_missing_dimensions_but_preserves_overrides():
    module = load_script_module()
    parsed = SimpleNamespace(preset="github-calendar", row=None, col="hour", unit=None, metric=None)

    result = module.apply_preset(parsed)

    assert result.row == "weekday"
    assert result.col == "hour"
    assert result.unit == "commit"
    assert result.metric == "count"


def test_author_day_matrix_filters_bots_and_sorts_by_volume():
    module = load_script_module()

    matrix = module.build_heatmap_matrix(sample_activity(), args())

    assert list(matrix.index) == ["alice", "bob"]
    assert matrix.loc["alice", "2026-05-04"] == 1
    assert matrix.loc["alice", "2026-05-05"] == 1
    assert matrix.loc["bob", "2026-05-05"] == 1
    assert "bot:github-actions" not in matrix.index


def test_weekday_hour_matrix_completes_calendar_axes():
    module = load_script_module()

    matrix = module.build_heatmap_matrix(sample_activity(), args(row="weekday", col="hour"))

    assert list(matrix.index) == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    assert list(matrix.columns) == [f"{hour:02d}" for hour in range(24)]
    assert matrix.loc["Mon", "09"] == 1
    assert matrix.loc["Tue", "10"] == 1


def test_category_day_churn_respects_category_order():
    module = load_script_module()

    matrix = module.build_heatmap_matrix(sample_activity(), args(row="category", col="date", metric="churn"))

    assert list(matrix.index)[:3] == ["feature_development", "bug_fix", "docs"]
    assert matrix.loc["bug_fix", "2026-05-05"] == 20


def test_impact_metrics_sum_like_heatmap_values():
    module = load_script_module()

    strategic = module.build_heatmap_matrix(sample_activity(), args(row="actor", col="date", metric="strategic_units"))
    risk = module.build_heatmap_matrix(sample_activity(), args(row="actor", col="date", metric="risk_score"))

    assert strategic.loc["alice", "2026-05-04"] == 1
    assert strategic.loc["alice", "2026-05-05"] == 1
    assert risk.loc["alice", "2026-05-04"] == 3
