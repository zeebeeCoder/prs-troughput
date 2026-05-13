# Delivery insight helper scripts

Reusable scripts that turn the local `prs-troughput` parquet lake into visual artifacts. These live with the skill so agents can copy/run them instead of inventing chart code from scratch.

## `temporal_heatmap.py`

Generic image generator for temporal heatmaps. It loads the canonical SQL assets:

1. `views/setup.sql`
2. `views/contributors.sql`
3. `views/work_attribution_macro.sql`
4. `views/temporal_activity.sql`

Install optional plotting dependencies with:

```bash
uv run --extra viz python skills/delivery-insights/scripts/temporal_heatmap.py --help
```

Examples:

```bash
# Contributors × days: daily commit density
uv run --extra viz python skills/delivery-insights/scripts/temporal_heatmap.py \
  --org Eve-World-Platform --repo coto-joy \
  --preset author-day --top-n-rows 12 \
  --output output/visualizations/coto-joy-author-day.png

# Work type × days: what kind of work landed when
uv run --extra viz python skills/delivery-insights/scripts/temporal_heatmap.py \
  --org Eve-World-Platform --repo coto-joy \
  --preset category-day --metric churn \
  --output output/visualizations/coto-joy-category-churn-day.png

# Contributors × days: strategic authored work only (not merge/deploy noise)
uv run --extra viz python skills/delivery-insights/scripts/temporal_heatmap.py \
  --org Eve-World-Platform --repo coto-joy \
  --preset author-day --metric strategic_units \
  --output output/visualizations/coto-joy-author-strategic-day.png

# Contributors × days: risk-weighted hotspots
uv run --extra viz python skills/delivery-insights/scripts/temporal_heatmap.py \
  --org Eve-World-Platform --repo coto-joy \
  --preset author-day --metric risk_score \
  --output output/visualizations/coto-joy-author-risk-day.png

# GitHub-style calendar for one contributor
uv run --extra viz python skills/delivery-insights/scripts/temporal_heatmap.py \
  --org Eve-World-Platform --repo coto-joy \
  --preset github-calendar --actors Zeebee \
  --output output/visualizations/coto-joy-zeebee-calendar.png

# Weekday × hour punchcard for the whole repo
uv run --extra viz python skills/delivery-insights/scripts/temporal_heatmap.py \
  --org Eve-World-Platform --repo coto-joy \
  --preset punchcard --annotate \
  --output output/visualizations/coto-joy-punchcard.png

# Compare multiple repos in one org, if local parquet exists
uv run --extra viz python skills/delivery-insights/scripts/temporal_heatmap.py \
  --org NFHotelAI --repo '*' \
  --preset repo-day --unit all \
  --output output/visualizations/nfhotelai-repo-day.png
```

Useful knobs:

- `--row actor|repo|category|unit_kind|weekday|hour|date|week|month|none`
- `--col actor|repo|category|unit_kind|weekday|hour|date|week|month|none`
- `--unit commit|pr|branch|all`
- `--metric count|churn|changed_files|strategic_units|operational_units|traced_units|untraced_units|untraced_churn|direct_main_units|direct_main_delivery_units|pr_linked_units|test_coverage_units|sensitive_units|generated_units|low_confidence_units|risk_score|risky_units|branch_ahead`
- `--actors name1,name2` / `--categories category1,category2`
- `--normalize row` for percent-of-row heatmaps

The script writes a normal image file (`.png`, `.svg`, `.pdf`, etc. depending on extension supported by matplotlib). Keep generated images under `output/` so they remain local artifacts.
