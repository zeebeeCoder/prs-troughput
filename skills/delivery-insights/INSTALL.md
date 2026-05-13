# Installing the `delivery-insights` skill

This skill lives at `skills/delivery-insights/` in the `prs-troughput` repo so it travels with the data layer. It is **not auto-loaded** — installing is an explicit act so the consumer chooses when to opt in.

## Option 1 — Bundle install via CLI (single command)

Self-extracting installer; bundles SKILL.md + INSTALL.md + VALIDATION.md + docs/ + views/ in one shot:

```bash
uv run pr-metrics --print-skill-bundle | bash -s ~/.claude/skills/delivery-insights
```

The script `mkdir -p`s and writes the skill docs, SQL views, and helper scripts. Pin the version by saving the output: `uv run pr-metrics --print-skill-bundle > install-skill.sh`.

## Option 2 — SKILL.md only via CLI

If you have the `prs-troughput` repo on disk and just need the skill manifest:

```bash
mkdir -p ~/.claude/skills/delivery-insights
uv run pr-metrics --print-skill > ~/.claude/skills/delivery-insights/SKILL.md
```

The skill body references docs/ + views/ — those still need to live in the working directory the agent operates in (i.e. you `cd /path/to/prs-troughput && claude`).

## Option 3 — Symlink

Keeps the skill in sync with the repo automatically:

```bash
mkdir -p ~/.claude/skills
ln -s "$(pwd)/skills/delivery-insights" ~/.claude/skills/delivery-insights
```

## Option 4 — Copy

Use a copy if you want to pin a specific version of the methodology:

```bash
mkdir -p ~/.claude/skills
cp -r skills/delivery-insights ~/.claude/skills/delivery-insights
```

Re-copy when the repo's playbook updates.

## Option 5 — Project-scoped

If you only want this skill active when working in this repo, copy or symlink to `.claude/skills/` instead:

```bash
mkdir -p .claude/skills
ln -s "$(pwd)/skills/delivery-insights" .claude/skills/delivery-insights
```

Claude Code auto-discovers skills under `.claude/skills/` when the working directory is this repo.

## Verifying the install

In a fresh Claude Code session inside (or outside) this repo, ask:
> "Use the delivery-insights skill to summarize the contributor mix for Eve-World-Platform/coto-joy over the last 90 days."

If the skill is loaded correctly, the agent should:
1. Reference reading `docs/analysis-playbook.md`.
2. Run `views/setup.sql` + `views/contributors.sql` before any analysis.
3. Use archetype labels from the playbook (e.g. "tactical_integrator") rather than improvised ones.
4. Flag any low-confidence attributions.

## Uninstalling

```bash
rm ~/.claude/skills/delivery-insights        # symlink or copy
# or
rm .claude/skills/delivery-insights          # project-scoped
```

## Dependencies

The skill assumes the working directory contains:
- `docs/data-contract.md`
- `docs/analysis-playbook.md`
- `views/*.sql`
- `scripts/temporal_heatmap.py` for optional image heatmaps

If those are missing, the skill is inert — it explicitly tells the agent to fail loudly rather than improvise.

Visualization helpers require optional plotting dependencies:

```bash
uv run --extra viz python scripts/temporal_heatmap.py --help
# or, from a checkout:
uv run --extra viz python skills/delivery-insights/scripts/temporal_heatmap.py --help
```
