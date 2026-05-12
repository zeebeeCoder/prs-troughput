# Views

Canonical DuckDB SQL queries for analyzing `prs-troughput` data. Reusable, parameterized, no Python required.

## Conventions

- Each `.sql` file is a **single canonical analysis shape**.
- All files use DuckDB syntax.
- Parameters are passed via DuckDB prepared-statement placeholders (`?`) or via `SET VARIABLE`.
- Each file documents its parameters in the header comment.
- Files assume `setup.sql` was run first (creates `*_latest` views and `contributors`).

## Usage

### From DuckDB CLI

```bash
duckdb < views/setup.sql          # run once per session
duckdb -cmd "$(cat views/setup.sql)" < views/work_attribution_macro.sql
```

### From Python

```python
import duckdb
con = duckdb.connect()
con.execute(open("views/setup.sql").read())
con.execute(open("views/contributors.sql").read())
result = con.execute(
    open("views/work_attribution_macro.sql").read(),
    {"org": "Eve-World-Platform", "repo": "coto-joy", "days_back": 90},
).fetchdf()
```

### From Claude Code (with the `delivery-insights` skill)

The skill handles loading order and parameter substitution. See `skills/delivery-insights/SKILL.md`.

## File index

| File | Lens (per playbook §0) | What it returns |
|---|---|---|
| `setup.sql` | — | Bootstraps `*_latest` views over raw parquet. Run first. |
| `contributors.sql` | — | Author identity normalization. Run second. Materializes `contributors` view. |
| `active_contributors.sql` | — | Everyone with ≥N units in window. Use this instead of top-N. |
| `work_attribution_macro.sql` | velocity / quality | Per-commit macro category via 6-signal cascade. The headline view. |
| `work_mix_per_author.sql` | velocity | Per-author × macro-category pivot for stacked-bar visualization. |
| `volume_vs_impact.sql` | quality | Per-author authored commits vs median churn vs traceability. |
| `punchcard.sql` | velocity | Per-author weekday × hour intensity. |
| `weekday_rollup.sql` | velocity | Per-author weekday distribution (hour collapsed). |
| `off_hours_work.sql` | quality / burnout | Per-author per-week % off-hours commits. |
| `invisible_wip_with_owner.sql` | lifecycle | Branches ahead of master + their head-commit author + idle days. |

## Adding a new view

1. Read `docs/analysis-playbook.md` first — does the analysis fit existing macro categories?
2. If yes, write a new SQL file. Header comment must include: purpose, parameters, expected lens, depends-on (which other view files).
3. Update this README's file index.
4. Add a usage example in the skill if it's leadership-relevant.

Do NOT inline contributor identity logic or attribution rules — extend `contributors.sql` / `work_attribution_macro.sql` instead.
