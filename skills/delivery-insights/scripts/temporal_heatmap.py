#!/usr/bin/env python3
"""Render temporal heatmap images from a prs-troughput parquet lake.

The script is intentionally generic: choose the delivery unit, row dimension,
column dimension, and metric at runtime. It uses the canonical SQL views shipped
with the delivery-insights skill, then writes a PNG/SVG/PDF image via
matplotlib.

Examples:
  # GitHub-style calendar: weekdays x weeks for one contributor
  uv run --extra viz python skills/delivery-insights/scripts/temporal_heatmap.py \
    --org Eve-World-Platform --repo coto-joy --preset github-calendar \
    --actors Zeebee --output output/visualizations/zeebee-calendar.png

  # Compare contributors by daily commit count
  uv run --extra viz python skills/delivery-insights/scripts/temporal_heatmap.py \
    --org Eve-World-Platform --repo coto-joy --preset author-day \
    --top-n-rows 12 --output output/visualizations/author-day.png

  # Work-type density by day
  uv run --extra viz python skills/delivery-insights/scripts/temporal_heatmap.py \
    --org Eve-World-Platform --repo coto-joy --preset category-day \
    --metric churn --output output/visualizations/category-churn-day.png
"""

from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
from typing import Iterable, Optional

import duckdb
import pandas as pd

WEEKDAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
CATEGORY_ORDER = [
    "feature_development",
    "refactoring",
    "testing",
    "bug_fix",
    "agent_tooling",
    "docs",
    "infra_deploy",
    "integration",
    "maintenance",
    "unclassified",
    "pr_merged",
    "pr_open",
    "pr_closed",
    "invisible_wip",
    "branch_with_open_pr",
    "branch_snapshot",
    "branch_baseline",
]
PRESETS = {
    "author-day": {
        "row": "actor",
        "col": "date",
        "unit": "commit",
        "metric": "count",
        "description": "contributors × calendar days",
    },
    "category-day": {
        "row": "category",
        "col": "date",
        "unit": "commit",
        "metric": "count",
        "description": "macro work categories × calendar days",
    },
    "repo-day": {
        "row": "repo",
        "col": "date",
        "unit": "all",
        "metric": "count",
        "description": "repositories × calendar days",
    },
    "github-calendar": {
        "row": "weekday",
        "col": "week",
        "unit": "commit",
        "metric": "count",
        "description": "GitHub-style weekdays × weeks calendar",
    },
    "punchcard": {
        "row": "weekday",
        "col": "hour",
        "unit": "commit",
        "metric": "count",
        "description": "weekday × hour-of-day density",
    },
    "unit-kind-day": {
        "row": "unit_kind",
        "col": "date",
        "unit": "all",
        "metric": "count",
        "description": "commits vs PRs vs branch snapshots by day",
    },
}
DIMENSIONS = ("actor", "repo", "category", "unit_kind", "weekday", "hour", "date", "week", "month", "none")
METRICS = (
    "count",
    "churn",
    "changed_files",
    "strategic_units",
    "operational_units",
    "traced_units",
    "untraced_units",
    "untraced_churn",
    "direct_main_units",
    "direct_main_delivery_units",
    "pr_linked_units",
    "test_coverage_units",
    "sensitive_units",
    "generated_units",
    "low_confidence_units",
    "risk_score",
    "risky_units",
    "branch_ahead",
)
UNITS = ("commit", "pr", "branch", "all")


def _parse_csv(value: Optional[str]) -> Optional[set[str]]:
    if not value:
        return None
    return {item.strip() for item in value.split(",") if item.strip()}


def _format_presets() -> str:
    return ", ".join(f"{name} ({cfg['description']})" for name, cfg in PRESETS.items())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render a temporal delivery-ledger heatmap image from local prs-troughput parquet data.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--org", required=True, help="GitHub organization, e.g. Eve-World-Platform")
    parser.add_argument("--repo", default="*", help="Repository name, or '*' for every repo in the org")
    parser.add_argument("--days-back", type=int, default=90, help="Window of activity to query")
    parser.add_argument("--preset", choices=sorted(PRESETS), default="author-day", help=f"Chart preset: {_format_presets()}")
    parser.add_argument("--row", choices=DIMENSIONS, default=None, help="Heatmap row dimension; overrides preset")
    parser.add_argument("--col", choices=DIMENSIONS, default=None, help="Heatmap column dimension; overrides preset")
    parser.add_argument("--unit", choices=UNITS, default=None, help="Delivery unit to include; overrides preset")
    parser.add_argument("--metric", choices=METRICS, default=None, help="Cell metric; overrides preset")
    parser.add_argument("--actors", default=None, help="Comma-separated actor filter after identity normalization")
    parser.add_argument("--categories", default=None, help="Comma-separated category filter")
    parser.add_argument("--include-bots", action="store_true", help="Include bot:* actors")
    parser.add_argument("--top-n-rows", type=int, default=12, help="Keep the N highest-volume rows; 0 keeps all rows")
    parser.add_argument("--normalize", choices=("none", "row"), default="none", help="Normalize cell values")
    parser.add_argument("--repo-root", default=None, help="Repo root containing output/; defaults to checkout root or cwd")
    parser.add_argument("--assets-root", default=None, help="Directory containing views/; defaults to skill bundle root, checkout root, or cwd")
    parser.add_argument("--output", default="output/visualizations/temporal-heatmap.png", help="Image path to write")
    parser.add_argument("--title", default=None, help="Custom chart title")
    parser.add_argument("--cmap", default="YlOrRd", help="Matplotlib color map")
    parser.add_argument("--width", type=float, default=None, help="Figure width in inches")
    parser.add_argument("--height", type=float, default=None, help="Figure height in inches")
    parser.add_argument("--dpi", type=int, default=140, help="Output DPI")
    parser.add_argument("--annotate", action="store_true", help="Write numeric values into cells")
    return parser


def apply_preset(args: argparse.Namespace) -> argparse.Namespace:
    preset = PRESETS[args.preset]
    for key in ("row", "col", "unit", "metric"):
        if getattr(args, key) is None:
            setattr(args, key, preset[key])
    return args


def _candidate_assets_roots(explicit: Optional[str]) -> Iterable[Path]:
    if explicit:
        yield Path(explicit)
    script_path = Path(__file__).resolve()
    # Installed skill bundle: <skill>/scripts/temporal_heatmap.py and <skill>/views/.
    yield script_path.parents[1]
    # Repo checkout: <repo>/skills/delivery-insights/scripts/temporal_heatmap.py and <repo>/views/.
    if len(script_path.parents) > 3:
        yield script_path.parents[3]
    yield Path.cwd()


def resolve_assets_root(explicit: Optional[str] = None) -> Path:
    for candidate in _candidate_assets_roots(explicit):
        root = candidate.expanduser().resolve()
        if (root / "views" / "setup.sql").is_file():
            return root
    raise FileNotFoundError(
        "Could not find views/setup.sql. Pass --assets-root pointing at the repo root or installed skill bundle."
    )


def resolve_repo_root(explicit: Optional[str] = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()

    script_path = Path(__file__).resolve()
    candidates = [Path.cwd()]
    if len(script_path.parents) > 3:
        candidates.append(script_path.parents[3])

    for candidate in candidates:
        root = candidate.expanduser().resolve()
        if (root / "output").exists():
            return root
    return Path.cwd().resolve()


def _read_view(assets_root: Path, name: str) -> str:
    path = assets_root / "views" / name
    if not path.is_file():
        raise FileNotFoundError(f"Missing required SQL view: {path}")
    return path.read_text()


def load_temporal_activity(args: argparse.Namespace) -> pd.DataFrame:
    assets_root = resolve_assets_root(args.assets_root)
    repo_root = resolve_repo_root(args.repo_root)
    params = {"org": args.org, "repo": args.repo, "days_back": args.days_back}

    previous_cwd = Path.cwd()
    os.chdir(repo_root)
    try:
        con = duckdb.connect()
        try:
            con.execute(_read_view(assets_root, "setup.sql"))
            con.execute(_read_view(assets_root, "contributors.sql"))
            attribution_sql = _read_view(assets_root, "work_attribution_macro.sql")
            con.execute("CREATE OR REPLACE TABLE attributed_commits AS " + attribution_sql, params)
            return con.execute(_read_view(assets_root, "temporal_activity.sql"), params).fetchdf()
        finally:
            con.close()
    finally:
        os.chdir(previous_cwd)


def _dimension_values(df: pd.DataFrame, dimension: str) -> pd.Series:
    if dimension == "none":
        return pd.Series(["all"] * len(df), index=df.index)
    if dimension == "date":
        return pd.to_datetime(df["activity_date"]).dt.strftime("%Y-%m-%d")
    if dimension == "week":
        return pd.to_datetime(df["week_start"]).dt.strftime("%Y-%m-%d")
    if dimension == "month":
        return pd.to_datetime(df["month_start"]).dt.strftime("%Y-%m")
    if dimension == "weekday":
        return df["weekday_label"].astype(str)
    if dimension == "hour":
        return df["hour_of_day"].astype(int).map(lambda hour: f"{hour:02d}")
    return df[dimension].fillna("unknown").astype(str)


def _axis_order(labels: Iterable[str], dimension: str) -> list[str]:
    labels_set = set(labels)
    if dimension == "weekday":
        return [label for label in WEEKDAY_ORDER if label in labels_set]
    if dimension == "hour":
        return [f"{hour:02d}" for hour in range(24) if f"{hour:02d}" in labels_set]
    if dimension == "category":
        known = [label for label in CATEGORY_ORDER if label in labels_set]
        unknown = sorted(labels_set - set(known))
        return known + unknown
    return sorted(labels_set)


def _complete_axis_order(labels: Iterable[str], dimension: str) -> list[str]:
    labels_set = set(labels)
    if dimension == "weekday":
        return WEEKDAY_ORDER
    if dimension == "hour":
        return [f"{hour:02d}" for hour in range(24)]
    if dimension == "category":
        known = [label for label in CATEGORY_ORDER if label in labels_set]
        unknown = sorted(labels_set - set(known))
        return known + unknown
    return _axis_order(labels_set, dimension)


def _filter_activity(df: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    filtered = df.copy()
    if args.unit != "all":
        filtered = filtered[filtered["unit_kind"] == args.unit]
    if not args.include_bots:
        filtered = filtered[~filtered["actor"].str.startswith("bot:", na=False)]

    actors = _parse_csv(args.actors)
    if actors:
        filtered = filtered[filtered["actor"].isin(actors)]

    categories = _parse_csv(args.categories)
    if categories:
        filtered = filtered[filtered["category"].isin(categories)]

    return filtered


def build_heatmap_matrix(df: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    filtered = _filter_activity(df, args)
    if filtered.empty:
        return pd.DataFrame()

    value_col = "units" if args.metric == "count" else args.metric
    work = filtered.copy()
    work["__row"] = _dimension_values(work, args.row)
    work["__col"] = _dimension_values(work, args.col)

    matrix = work.pivot_table(
        index="__row",
        columns="__col",
        values=value_col,
        aggfunc="sum",
        fill_value=0,
    )

    if matrix.empty:
        return matrix

    row_order = _complete_axis_order(matrix.index, args.row)
    col_order = _complete_axis_order(matrix.columns, args.col)
    matrix = matrix.reindex(index=row_order, columns=col_order, fill_value=0)

    if args.top_n_rows and args.row not in {"weekday", "hour", "date", "week", "month", "category", "unit_kind", "none"}:
        top_rows = matrix.sum(axis=1).sort_values(ascending=False).head(args.top_n_rows).index
        matrix = matrix.loc[top_rows]

    if args.normalize == "row":
        row_totals = matrix.sum(axis=1).replace(0, pd.NA)
        matrix = matrix.div(row_totals, axis=0).fillna(0) * 100

    return matrix


def _auto_size(matrix: pd.DataFrame, args: argparse.Namespace) -> tuple[float, float]:
    width = args.width or min(max(8.5, len(matrix.columns) * 0.32 + 2.4), 32)
    height = args.height or min(max(4.0, len(matrix.index) * 0.42 + 2.2), 28)
    return width, height


def _tick_positions(count: int, max_ticks: int = 28) -> list[int]:
    if count <= max_ticks:
        return list(range(count))
    step = int(math.ceil(count / max_ticks))
    return list(range(0, count, step))


def _format_value(value: float, normalize: str) -> str:
    if normalize == "row":
        return f"{value:.0f}%"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}"


def render_heatmap(matrix: pd.DataFrame, args: argparse.Namespace) -> Path:
    if matrix.empty:
        raise SystemExit("No rows matched the requested temporal heatmap filters.")

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:  # pragma: no cover - depends on optional environment
        raise SystemExit(
            "matplotlib is required for image output. Run with `uv run --extra viz ...` "
            "or install matplotlib in your environment."
        ) from exc

    width, height = _auto_size(matrix, args)
    fig, ax = plt.subplots(figsize=(width, height))
    image = ax.imshow(matrix.to_numpy(dtype=float), aspect="auto", cmap=args.cmap, interpolation="nearest")

    x_positions = _tick_positions(len(matrix.columns))
    ax.set_xticks(x_positions)
    ax.set_xticklabels([matrix.columns[pos] for pos in x_positions], rotation=90 if args.col in {"date", "week", "month"} else 45, ha="right")
    ax.set_yticks(range(len(matrix.index)))
    ax.set_yticklabels(matrix.index)

    title = args.title or (
        f"{args.org}/{args.repo} — {args.metric} by {args.row} × {args.col} "
        f"({args.unit} units, last {args.days_back}d)"
    )
    ax.set_title(title, loc="left", fontsize=12, pad=12)
    ax.set_xlabel(args.col)
    ax.set_ylabel(args.row)
    ax.grid(False)

    label = args.metric if args.normalize == "none" else f"{args.metric} (% of row)"
    fig.colorbar(image, ax=ax, label=label, shrink=0.85)

    if args.annotate and matrix.size <= 500:
        values = matrix.to_numpy(dtype=float)
        threshold = values.max() * 0.55 if values.size else 0
        for row_idx in range(values.shape[0]):
            for col_idx in range(values.shape[1]):
                value = values[row_idx, col_idx]
                if value == 0:
                    continue
                color = "white" if value >= threshold else "black"
                ax.text(col_idx, row_idx, _format_value(value, args.normalize), ha="center", va="center", fontsize=8, color=color)

    output_path = Path(args.output).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(output_path, dpi=args.dpi, bbox_inches="tight")
    plt.close(fig)
    return output_path


def main(argv: Optional[list[str]] = None) -> None:
    args = apply_preset(build_parser().parse_args(argv))
    df = load_temporal_activity(args)
    matrix = build_heatmap_matrix(df, args)
    output_path = render_heatmap(matrix, args)
    print(f"wrote {output_path}")
    print("source: views/setup.sql + views/contributors.sql + views/work_attribution_macro.sql + views/temporal_activity.sql")
    print(f"shape: {matrix.shape[0]} rows × {matrix.shape[1]} columns")


if __name__ == "__main__":
    main()
