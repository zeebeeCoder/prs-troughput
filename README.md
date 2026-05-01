# PR Metrics

A modern CLI tool for collecting and analyzing Pull Request metrics from GitHub organizations.

## Features

- 📊 **Comprehensive PR Analytics** - Volume, time, size, and team metrics across your organization
- 👥 **Contributor Performance Reports** - Deep-dive into individual developer activity, review participation, and merge patterns
- 🏥 **Repository Health Indicators** - Bus factor risk, review culture assessment, and team collaboration metrics
- 🎨 **Rich Terminal Reports** - Color-coded insights with visual progress bars and trend arrows
- 📈 **Weekly Trend Analysis** - Track contributor performance over time with historical comparisons
- 📏 **Organization Baselines** - Compare individual/repo performance against org-wide averages
- 💾 **Efficient Storage** - Hive-partitioned Parquet files with CSV exports for compatibility
- 📦 **Git Delivery Ledger** - Optional commit and branch snapshots expose direct-to-main work and invisible WIP
- ⚡ **Fast & Efficient** - Uses GitHub CLI (`gh`) for optimized API access

## Prerequisites

- **Python 3.9+**
- **[uv](https://docs.astral.sh/uv/)** - Fast Python package manager
- **[GitHub CLI (gh)](https://cli.github.com/)** - Authenticated with your GitHub account

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Authenticate with GitHub
gh auth login
```

## Quick Start

```bash
# Clone the repository
cd prs-troughput

# Run with uv (no installation needed!)
uv run pr-metrics --org your-org --days 30
```

That's it! `uv` automatically handles all dependencies.

## Usage

### Basic Commands

```bash
# Collect data for organization (last 14 days)
uv run pr-metrics --org your-org

# Collect data for last 30 days
uv run pr-metrics --org your-org --days 30

# Generate organization-wide terminal report
uv run pr-metrics --org your-org --report --terminal

# Generate contributor performance report for specific repository
uv run pr-metrics --org your-org --repo backend-api --days 60 --report --terminal

# Full repository scan (slower, more complete)
uv run pr-metrics --org your-org --full-scan --days 30

# Collect PRs plus commit/branch ledger data for one or more repositories
uv run pr-metrics --org your-org --repo backend-api --days 30 --include-ledger
uv run pr-metrics --org your-org --repo coto_joy,coto_backend --days 30 --include-ledger

# Generate combined delivery report from collected PR/commit/branch data
uv run pr-metrics --org your-org --repo backend-api --days 30 --delivery-report
uv run pr-metrics --org your-org --repo backend-api --days 30 --delivery-report --branch-active-days 14

# Run reusable DuckDB insight slices over the generated parquet lake
uv run pr-metrics --list-insights
uv run pr-metrics --org your-org --insight active_repos --days 90
uv run pr-metrics --org your-org --repo backend-api --insight kinetics_weekly --days 30
uv run pr-metrics --org your-org --repo backend-api --insight direct_main_risk --format json

# Validate GitHub API parquet facts against a local clone without mutating it
uv run pr-metrics --org your-org --repo backend-api --days 30 --validate-local ~/code/backend-api
```

### Command Line Options

| Option | Default | Description |
|--------|---------|-------------|
| `--org ORG` | (required*) | GitHub organization to analyze |
| `--repo REPO` | None | Filter by specific repository; collection accepts comma-separated names |
| `--days DAYS` | 14 | Number of days back to analyze |
| `--min-prs N` | 3 | Minimum PRs required to include repo |
| `--full-scan` | False | Process all repos (slower) |
| `--report` | False | Generate report from existing data |
| `--terminal` | False | Rich terminal report with styling |
| `--top-n N` | 5 | Top contributors in weekly breakdown |
| `--include-ledger` | False | Collect commit and branch ledger datasets in addition to PRs |
| `--include-commits` | False | Collect default-branch commit facts only |
| `--include-branches` | False | Collect remote branch snapshots only |
| `--commit-limit N` | 100 | Max default-branch commits to collect per repo |
| `--branch-limit N` | 100 | Max branches to collect per repo |
| `--skip-commit-files` | False | Skip per-file commit facts to reduce GitHub API work |
| `--branch-active-days N` | 30 | Treat branches with commits in this many days as active WIP |
| `--delivery-report` | False | Show combined merged PR + direct main commit + branch WIP report |
| `--list-insights` | False | List reusable DuckDB insight slices |
| `--insight NAME` | None | Run a named insight slice from existing parquet data |
| `--format table/json/csv` | table | Output format for `--insight` and `--validate-local` |
| `--validate-local PATH` | None | Compare existing parquet commit/branch facts against a local Git clone with read-only commands |
| `--remote REMOTE` | origin | Remote-tracking namespace for `--validate-local` branch checks |

\* Organization is required via `--org` flag or `PR_METRICS_ORG` environment variable

### Configuration

Set default organization via environment variable:

```bash
export PR_METRICS_ORG="my-org"
uv run pr-metrics  # Uses my-org
uv run pr-metrics --org another-org  # Override to another-org
```

### 👥 Contributor Performance Reports

When you specify a repository with `--repo`, the tool automatically generates a **contributor-focused report** with enhanced metrics:

```bash
uv run pr-metrics --org your-org --repo your-repo --days 30 --report --terminal
```

**What you get:**
- **📊 Contributor Rankings** - Detailed table showing all contributors with PR count, merge rate, average merge time, review participation, and self-merge rate
- **📏 Organization Baseline** - Compare individual contributors against org-wide averages for merge rate, time, and size
- **📈 Weekly Trends** - Individual contributor deep-dives showing week-over-week performance patterns with trend arrows (↑↓→)
- **🏥 Health Indicators**:
  - **Bus Factor Risk** - Are contributions concentrated in too few people?
  - **Review Culture** - What percentage of PRs are self-merged vs peer-reviewed?
  - **Review Participation** - How many contributors actively review others' code?

**Perfect for:**
- 🎯 Performance reviews and 1-on-1s
- 📋 Sprint retrospectives
- 👥 Team capacity planning
- 🔍 Identifying process bottlenecks
- 🏆 Recognizing top contributors
- ⚠️ Spotting collaboration issues early

See [docs/CONTRIBUTOR_METRICS.md](docs/CONTRIBUTOR_METRICS.md) for detailed documentation.

## Metrics Collected

### 📊 Volume Metrics
- Total PRs created/merged/closed
- Daily throughput rate
- Merge success rate

### ⏱️ Time Metrics
- Average time to merge
- Time to first review
- Weekly trend analysis

### 📏 Size & Complexity
- PR size distribution (small/medium/large)
- Average lines changed
- Commits per PR

### 👥 Team & Collaboration Metrics
- Contributions per author with merge rates
- Individual weekly performance trends
- Review participation (who reviews whose code)
- Self-merge vs peer-review rates
- Review responsiveness (time to first review)
- Repository activity and health indicators

### 📦 Git Delivery Ledger Metrics
- PR raw fields for queue health: `updated_at`, `head_ref`, `head_sha`, review requests, CI status, mergeability
- Default-branch commits with Conventional Commit parsing and activity classes
- Direct-to-main commit lane separated from PR-linked squash/merge commits when detectable
- Branch snapshots with ahead/behind counts and open-PR linkage
- Active invisible WIP: branches ahead of default branch without an open PR, filtered by recent branch activity
- Stale branch WIP bucket so old long-lived branches do not swamp the live queue

### 🧠 DuckDB Insight Slices

The CLI is primarily a data-refresh engine, but it also exposes reusable SQL-backed slices for agents and analysts. These operate on canonical `*_latest` DuckDB views over Hive-partitioned parquet.

| Insight | Purpose |
|---------|---------|
| `active_repos` | Pick evaluation repos by recent PR intensity |
| `intensity_weekly` | Weekly heatmap grain by repo, actor, and lane |
| `kinetics_weekly` | Velocity and acceleration/deceleration signals by repo/week |
| `review_queue` | Open PR queue buckets: review, author, CI, mergeability, stale |
| `invisible_wip` | Branches ahead of default branch without open PRs |
| `direct_main_risk` | Direct-main commits ranked by churn/sensitive/no-test risk |
| `traceability` | Task/spec marker coverage across PRs, commits, and branches |
| `activity_mix` | Semantic activity classes by repo |

### 🔎 Local Accuracy Validation

Use `--validate-local` when you have a local clone and want to compare GitHub API-derived parquet facts with Git's own view of the repository:

```bash
uv run pr-metrics --org Eve-World-Platform \
  --repo coto-joy \
  --days 30 \
  --validate-local ~/code/coto/coto-joy
```

The validator intentionally runs only read-only commands (`git cat-file`, `git show --numstat`, `git rev-list`, `git rev-parse`). It does **not** fetch, checkout, reset, commit, or write into the target repo. If the local clone is stale, rows are reported as missing/not comparable instead of being corrected automatically.

## Output

### Terminal Report

```bash
uv run pr-metrics --report --terminal
```

Shows interactive dashboard with:
- Color-coded success rates
- Visual progress bars
- Weekly performance trends
- Top contributor breakdowns

### Data Files

Data is automatically saved using **Hive partitioning** for efficient querying and schema evolution:

```
output/data/
├── org=your-org/
│   ├── repo=backend-api/
│   │   ├── year=2025/
│   │   │   ├── month=10/
│   │   │   │   └── data_0.parquet
│   │   │   └── month=11/
│   │   │       └── data_0.parquet
│   └── repo=mobile-app/
│       └── year=2025/
│           └── month=10/
│               └── data_0.parquet
```

**Benefits:**
- ⚡ Fast filtering by organization, repository, year, or month
- 🔄 Schema evolution support (old and new data coexist)
- 💾 Efficient storage with columnar Parquet format
- 📊 Direct DuckDB querying without loading everything into memory

Legacy CSV backups are also saved for compatibility:
```
output/pr_data_org-name_20251020_143021.csv
```

## Installation Options

### 1. Use with `uv run` (Recommended)

No installation needed - just run:
```bash
uv run pr-metrics --org my-org
```

### 2. Install as Global Tool

```bash
uv tool install .
pr-metrics --org my-org  # Now available globally
```

### 3. Editable Install (Development)

```bash
uv venv
source .venv/bin/activate
uv pip install -e .
```

## Use Cases

### For Engineering Managers
- 👥 **Performance Reviews** - Data-driven insights for 1-on-1s with contributor rankings and weekly trends
- 🎯 **Team Planning** - Identify capacity constraints and workload distribution
- ⚠️ **Risk Management** - Monitor bus factor and contributor concentration
- 🏆 **Recognition** - Identify top performers and review champions

### For Team Leads
- 📋 **Sprint Retrospectives** - Weekly velocity tracking with trend indicators
- 🔍 **Bottleneck Detection** - Find PR review delays and merge time issues
- 🤝 **Collaboration Health** - Track review participation and self-merge rates
- 📊 **Process Optimization** - Compare against org baselines to set improvement targets

### For Individual Contributors
- 📈 **Personal Metrics** - Track your own PR performance over time
- 🎓 **Growth Tracking** - Monitor improvements in merge rate, PR size, and review time
- 🤝 **Team Contribution** - See how your review participation compares

### For Organizations
- 📊 **Organization-wide Analytics** - Cross-repo metrics and throughput trends
- 📏 **Baseline Establishment** - Set realistic targets based on historical data
- 🔄 **Historical Comparison** - Track improvement initiatives over time
- 📦 **Repository Health** - Identify repos needing process improvement

## Example Output

### Data Collection
```
🔍 Collecting PR metrics for your-org (last 14 days)
📁 Found 15 repositories with recent PR activity

  1/15: backend-api
  2/15: mobile-app
  3/15: frontend-web

🎯 RESULTS:
   Total PRs: 127
   Merged: 98 (77.2%)
   Daily throughput: 7.0 PRs/day
   Avg PR size: 423 lines
   Avg time to merge: 4.2 hours
   Top authors: {'dev1': 23, 'dev2': 18, 'dev3': 15}

💾 Data saved to Hive partitions: output/data/
   Legacy CSV backup: output/pr_data_your-org_20251020_143021.csv
```

### Contributor Performance Report (with `--repo`)
```
╭──────────────────────────────── 📊 Overview ─────────────────────────────────╮
│ Contributor Performance Report                                               │
│ your-org / backend-api                                                       │
│                                                                              │
│ Repository Scope:                                                            │
│ • Date Range: 2025-09-01 to 2025-10-21 (51 days)                            │
│ • Contributors: 8 developers                                                 │
│ • Total PRs: 156 (92.3% merged)                                              │
╰──────────────────────────────────────────────────────────────────────────────╯

╭────────────────────────────── 📏 Org Baseline ───────────────────────────────╮
│ Organization Averages (for comparison):                                      │
│ • Merge Rate: 88.5%                                                          │
│ • Merge Time: 18.2h                                                          │
│ • PR Size: 324 lines                                                         │
╰──────────────────────────────────────────────────────────────────────────────╯

                              Contributor Rankings
╭────────┬─────┬────────┬────────┬────────┬────────┬────────┬────────┬─────────╮
│ Author │ PRs │ Merged │  Rate  │   Time │   Size │ Reviews│ Self-% │ vs Org  │
├────────┼─────┼────────┼────────┼────────┼────────┼────────┼────────┼─────────┤
│ alice  │  45 │   43   │ 95.6%  │  12.3h │    287 │   12   │ 14.0%  │    ↑    │
│ bob    │  38 │   35   │ 92.1%  │  15.8h │    412 │    8   │ 20.0%  │    ↑    │
│ carol  │  29 │   27   │ 93.1%  │  21.4h │    198 │    5   │  7.4%  │    →    │
╰────────┴─────┴────────┴────────┴────────┴────────┴────────┴────────┴─────────╯

╭─────────────────────────── 🏥 Health Check ──────────────────────────────────╮
│ Repository Health Indicators:                                                │
│ ✓ Good Balance: Top 20% of contributors = 28.8% of PRs                       │
│ ✓ Good Review Culture: 15.4% self-merged                                     │
│ ✓ Active Review Participation: 62% review others                             │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## Troubleshooting

**Authentication errors**
```bash
gh auth status
gh auth login  # If not authenticated
```

**No data found**
- Check organization access
- Verify repository permissions
- Try `--full-scan` for complete repo list

**Rate limits**
- Use `--min-prs` to filter repos
- Reduce `--days` for shorter time window

## License

MIT
