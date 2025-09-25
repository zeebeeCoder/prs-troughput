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
# Default: Analyze last 14 days, all repositories
python3 pr_metrics.py

# Analyze last 7 days
python3 pr_metrics.py --days 7

# Test with first 5 repositories only
python3 pr_metrics.py --limit 5

# Weekly sprint analysis
python3 pr_metrics.py --days 7 --limit 10
```

### Command Line Options

| Option | Default | Description |
|--------|---------|-------------|
| `--days` | 14 | Number of days back to analyze |
| `--limit` | None | Limit number of repositories to process |

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
Timestamped JSON files saved to `output/` directory:
```
output/pr_metrics_eve-world-platform_20250925_081334.json
```

#### Report Structure
```json
{
  "metadata": {
    "org": "Eve-World-Platform",
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

## Configuration

To analyze a different organization, edit the `ORG` variable in `pr_metrics.py`:
```python
ORG = "your-org-name"
```

## Example Output

```
🔍 Collecting PR metrics for Eve-World-Platform (last 14 days)...
📁 Found 100 repositories, processing 3

📊 Processing coto_backend (1/3)...
   📈 30 PRs (24 merged, 80.0% rate)
   👥 Top authors: {'srikar-samudrala': 16, 'nopanz': 4}
   ⏱️  Avg merge: 3.09h, First review: 1.91h
   📏 Avg PR size: 634 lines (5.1 commits)

🎯 ORG SUMMARY (Eve-World-Platform) - Last 14 days:
   Total PRs: 64
   Merged: 50 (78.1%)
   Daily throughput: 3.57 merged PRs/day

💾 Report saved to: output/pr_metrics_eve-world-platform_20250925_081334.json
```

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