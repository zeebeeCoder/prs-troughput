# PR Metrics

A modern CLI tool for collecting and analyzing Pull Request metrics from GitHub organizations.

## Features

- 📊 Comprehensive PR analytics (volume, time, size, team metrics)
- 🎨 Rich terminal reports with color-coded insights
- 📈 Weekly trend analysis and contributor breakdowns
- 💾 Export data to Parquet and CSV formats
- ⚡ Fast and efficient using GitHub CLI (`gh`)

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
# Analyze default organization (last 14 days)
uv run pr-metrics

# Analyze specific organization
uv run pr-metrics --org microsoft

# Analyze last 30 days
uv run pr-metrics --days 30

# Generate terminal report from existing data
uv run pr-metrics --report --terminal

# Full repository scan (slower, more complete)
uv run pr-metrics --full-scan --days 30
```

### Command Line Options

| Option | Default | Description |
|--------|---------|-------------|
| `--org ORG` | Eve-World-Platform | GitHub organization to analyze |
| `--days DAYS` | 14 | Number of days back to analyze |
| `--min-prs N` | 3 | Minimum PRs required to include repo |
| `--full-scan` | False | Process all repos (slower) |
| `--report` | False | Generate report from existing data |
| `--terminal` | False | Rich terminal report with styling |
| `--top-n N` | 5 | Top contributors in weekly breakdown |

### Configuration

Set default organization via environment variable:

```bash
export PR_METRICS_ORG="my-org"
uv run pr-metrics  # Uses my-org
uv run pr-metrics --org another-org  # Override to another-org
```

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

### 👥 Team Metrics
- Contributions per author
- Individual weekly performance
- Repository activity

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

Data is saved to `output/` directory:
```
output/pr_data_org-name_20251020_143021.parquet
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

- **Sprint retrospectives** - Weekly team velocity
- **Performance tracking** - Monthly throughput trends
- **Process optimization** - Identify bottlenecks
- **Team insights** - Contributor patterns
- **Historical analysis** - Compare metrics over time

## Example Output

```
🔍 Collecting PR metrics for microsoft (last 14 days)
🎯 Found 15 repositories with recent PR activity

  1/15: typescript
  2/15: vscode
  3/15: PowerToys

🎯 RESULTS:
   Total PRs: 127
   Merged: 98 (77.2%)
   Daily throughput: 7.0 PRs/day
   Avg PR size: 423 lines
   Avg time to merge: 4.2 hours
   Top authors: {'user1': 23, 'user2': 18, 'user3': 15}

💾 Data saved:
   output/pr_data_microsoft_20251020_143021.parquet
   output/pr_data_microsoft_20251020_143021.csv
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
