---
name: delivery-insights
description: Use this skill when analyzing contributor performance, work attribution, velocity, quality, lifecycle, or agentic engineering on data collected by the prs-troughput tool. Required reading before producing any insight from output/ledger/ parquet. Covers the macro work taxonomy, 6-signal attribution cascade, and contributor archetypes documented in docs/analysis-playbook.md.
---

# Delivery Insights — methodology contract

You are analyzing data collected by `prs-troughput`, a Git delivery ledger that produces parquet under `output/ledger/`. The data layer is rich (5 grains, 13 named insights, 6 attribution signals); the analytical edge — *how to look at this data* — lives in this skill plus the in-repo docs.

**This is a prescriptive skill.** Improvising methodology silently miscounts contributors and produces leadership reports that look authoritative but are wrong. Follow the contract.

## Before you start

1. Read `docs/data-contract.md` in the repo root for schema reference.
2. Read `docs/analysis-playbook.md` in full for methodology — macro taxonomy, signal cascade, archetypes, reporting hygiene.
3. Bootstrap your DuckDB session by running, in order:
   - `views/setup.sql` (creates `*_latest` views)
   - `views/contributors.sql` (canonical author identity — extend the manual overrides for your repo if new collisions appear)

If any of these files are missing, the data layer hasn't been set up — do not improvise replacements; tell the user.

## Picking the right view for the question

Consult the four-lens table in `docs/analysis-playbook.md` §0:

| User asks | Lens | Run |
|---|---|---|
| "How fast is the team shipping?" | velocity | `views/punchcard.sql` + `views/weekday_rollup.sql` + (existing CLI insight `kinetics_weekly`) |
| "Who's doing what kind of work?" | velocity / quality | `views/work_attribution_macro.sql` → `views/work_mix_per_author.sql` |
| "Is the team trading speed for risk?" | quality | `views/volume_vs_impact.sql` + (existing CLI insights `direct_main_risk`, `review_queue`) |
| "Where is hidden work?" | lifecycle | `views/invisible_wip_with_owner.sql` + (existing CLI insight `untraced_units`) |
| "Is anyone burning out?" | quality | `views/off_hours_work.sql` |
| "How is AI-assisted work showing up?" | agentic | `views/work_attribution_macro.sql`, filter to `primary_label = 'agent_tooling'` |

If a question doesn't fit, **map it to the closest lens before running queries**. Do not invent new analysis shapes — propose extending the playbook.

## Running attributed-commit views

`work_mix_per_author.sql` and `volume_vs_impact.sql` depend on a materialized `attributed_commits` table. Standard pipeline:

```python
import duckdb
con = duckdb.connect()
con.execute(open("views/setup.sql").read())
con.execute(open("views/contributors.sql").read())
con.execute(
    "CREATE OR REPLACE TABLE attributed_commits AS " + open("views/work_attribution_macro.sql").read(),
    {"org": ORG, "repo": REPO, "days_back": 90},
)
work_mix = con.execute(
    open("views/work_mix_per_author.sql").read(),
    {"min_commits": 5},
).fetchdf()
```

## Reporting hygiene (mandatory)

Every output you produce MUST include:

1. **Window**: state which `days_back` was used (e.g. "Eve-World-Platform/coto-joy, last 90 days").
2. **Source views**: list the view filenames you queried.
3. **Identity normalization confirmation**: state "Author identity normalized via `views/contributors.sql`" once per report.
4. **Confidence threshold**: when reporting attributed commits, flag any with `confidence < 0.7` as "low confidence — needs human review."
5. **Archetype labels**: use only the labels from playbook §3 (`pure_builder`, `caretaker_owner`, `tactical_integrator`, `bug_fix_specialist`, `quality_ops`, `agent_collaborator`, `insufficient_data`). Don't invent paraphrases.
6. **Lens**: state which of the four lenses the analysis is operating in.

## Anti-patterns — refuse these

- ❌ Adding `LIMIT N` to a contributor list without a justification you can show the user. Use `views/active_contributors.sql` to enumerate everyone above an activity floor.
- ❌ Inlining `CASE WHEN lower(author_name) IN (...)` for identity. Extend `views/contributors.sql`.
- ❌ Reading raw parquet via `read_parquet('output/ledger/**/*.parquet')` without dedup. Use `*_latest` views.
- ❌ Inventing macro categories. The taxonomy is in playbook §1; extend it via PR, not in the moment.
- ❌ Reporting commit count alone. Always pair with impact — see playbook §5.
- ❌ Naming individuals in a burnout-signal report. Frame as patterns; the leader will translate to names.
- ❌ Producing a chart without being able to point at the SQL view it was generated from.

## When extending

If a question genuinely doesn't fit the existing views:

1. Consider whether the playbook needs a new lens or category — propose the extension first.
2. If a new view is justified, add it under `views/` with a clear header comment (purpose, parameters, depends-on, expected lens).
3. Update `views/README.md` index.
4. Update this `SKILL.md` lens table if leadership-relevant.

Do NOT fork the cascade. If a 7th attribution signal is needed, add it to `work_attribution_macro.sql` with appropriate weight.

## Visualization

The data layer doesn't render — **outer agents own visualization**. Choose any library (matplotlib, plotly, altair, vega-lite, terminal blocks). Two examples for reference:

- `output/stress-test-2026-05-08/punchcard_demo.py` — matplotlib heatmap from `views/punchcard.sql`
- `output/attribution-experiment-2026-05-08/visualize.py` — stacked bars + bubble charts from attributed commits

Keep visualization scripts under `output/<analysis-name>/` so they don't pollute the data-layer repo.

## Provenance

Methodology derived from:
- **2026-05-08-T0002** (stress test on coto-joy, 90d) — surfaced data-quality findings, identity collisions, the LIMIT-N footgun.
- **2026-05-08-T0003** (multi-signal attribution experiment) — validated the cascade at 96.7% spot-check accuracy, defined the archetypes from observed patterns.
- **2026-05-08-T0004** (this skill + docs + views) — encapsulation.

When updating methodology, cite the experiment / data that supports the change.
