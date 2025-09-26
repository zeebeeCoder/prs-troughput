# PR Throughput Metrics Tool

A comprehensive CLI tool for collecting Pull Request throughput metrics from GitHub organizations using the `gh` CLI. Specifically designed for tracking development velocity and team performance.

## Prerequisites

- **GitHub CLI (`gh`)** installed and authenticated
- **Python 3.7+**
- Access to the target GitHub organization

## Quick Start

1. **Clone/download** the script
2. **Authenticate with GitHub CLI:**
   ```bash
   gh auth login
   ```
3. **Run the tool:**
   ```bash
   python3 pr_metrics.py
   ```

## Usage

### Basic Commands

```bash
# Default: Analyze last 14 days, default organization
python3 pr_metrics.py

# Analyze different organization
python3 pr_metrics.py --org "microsoft"

# Analyze last 7 days for specific org
python3 pr_metrics.py --org "google" --days 7

# Test with minimum repo filter
python3 pr_metrics.py --min-prs 5

# Weekly sprint analysis
python3 pr_metrics.py --org "your-org" --days 7 --min-prs 1
```

### Command Line Options

| Option | Default | Description |
|--------|---------|-------------|
| `--days` | 14 | Number of days back to analyze |
| `--min-prs` | 3 | Minimum PRs required to include repo in report |
| `--org` | Eve-World-Platform | GitHub organization to analyze |
| `--full-scan` | False | Process all repos instead of just active ones |
| `--report` | False | Generate report from existing data |
| `--terminal` | False | Generate terminal-friendly report with rich styling |

## Metrics Collected

### 📊 **Volume Metrics**
- Total PRs created
- Merged/closed/open/draft counts
- Daily throughput rate
- Merge success rate

### ⏱️ **Time Metrics**
- Average time to merge
- Average time to first review
- Review cycle duration

### 📏 **Size & Complexity**
- PR size distribution (small/medium/large/xl)
- Average lines changed per PR
- Average commits per PR
- Review cycles needed

### 👥 **Team Metrics**
- Contributions per author
- Review decisions (approved/changes requested)
- Label usage patterns

## Output

### Terminal Display
Real-time progress with summary metrics for each repository and organization totals.

### JSON Reports
Timestamped data files saved to `output/` directory:
```
output/pr_data_your-org-name_20250925_081334.parquet
output/pr_data_your-org-name_20250925_081334.csv
```

#### Report Structure
```json
{
  "metadata": {
    "org": "your-organization-name",
    "generated_at": "2025-09-25T08:13:25",
    "days_analyzed": 14,
    "total_repos_in_org": 100
  },
  "repositories": {
    "repo-name": {
      "total_prs": 30,
      "merged_prs": 24,
      "merge_rate_percent": 80.0,
      "avg_time_to_merge_hours": 3.09,
      "avg_pr_size": 634.4,
      "authors": {...}
    }
  },
  "org_summary": {
    "total_prs": 64,
    "daily_throughput": 3.57,
    "top_contributors": {...}
  }
}
```

## Organization Configuration

### Multiple Ways to Set Organization

1. **Command Line Flag** (highest priority):
```bash
python3 pr_metrics.py --org "your-org-name"
```

2. **Environment Variable**:
```bash
export PR_METRICS_ORG="your-org-name"
python3 pr_metrics.py
```

3. **Default Fallback**: Eve-World-Platform (if no override specified)

### Advanced Usage

```bash
# Generate reports from existing data for specific org
python3 pr_metrics.py --report --org "microsoft" --terminal

# Compare different time periods for same org
python3 pr_metrics.py --org "google" --days 30
python3 pr_metrics.py --org "google" --days 7

# Environment variable with override
export PR_METRICS_ORG="default-org"
python3 pr_metrics.py                    # Uses default-org
python3 pr_metrics.py --org "temp-org"   # Uses temp-org
```

## Example Output

```
🔍 Collecting PR metrics for microsoft (last 14 days)...
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
   output/pr_data_microsoft_20250926_143021.parquet
   output/pr_data_microsoft_20250926_143021.csv
```

### Rich Terminal Reports

```bash
# Generate enhanced terminal report
python3 pr_metrics.py --report --org "microsoft" --terminal
```

Displays interactive dashboard with:
- Organization-specific metrics
- Visual progress bars
- Color-coded success rates
- Weekly trend analysis

## Use Cases

- **Sprint retrospectives** - Weekly team velocity analysis
- **Performance tracking** - Monthly throughput trends
- **Process optimization** - Identify review bottlenecks
- **Team insights** - Contributor activity and patterns
- **Historical analysis** - Compare metrics over time using saved JSON reports

## Troubleshooting

- **Authentication errors**: Run `gh auth status` to verify login
- **API rate limits**: Use `--limit` to process fewer repositories
- **No data**: Check organization access and repository permissions