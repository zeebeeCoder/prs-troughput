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
```

### Command Line Options

| Option | Default | Description |
|--------|---------|-------------|
| `--org ORG` | (required*) | GitHub organization to analyze |
| `--repo REPO` | None | Filter by specific repository (enables contributor report) |
| `--days DAYS` | 14 | Number of days back to analyze |
| `--min-prs N` | 3 | Minimum PRs required to include repo |
| `--full-scan` | False | Process all repos (slower) |
| `--report` | False | Generate report from existing data |
| `--terminal` | False | Rich terminal report with styling |
| `--top-n N` | 5 | Top contributors in weekly breakdown |

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

See [INSTALL.md](INSTALL.md) for detailed installation instructions.

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
