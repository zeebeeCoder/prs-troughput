# Contributor Performance Metrics

## Overview

The contributor performance feature provides deep insights into individual developer activity within a specific repository. When you scope analysis to a single repository using the `--repo` flag, the tool automatically generates a contributor-focused report with enhanced metrics and comparisons.

## Features

### 🎯 What You Get

1. **Contributor Rankings** - Comprehensive table showing all contributors with:
   - PR count (created vs. merged)
   - Merge rate (% of PRs that get merged)
   - Average merge time
   - Average PR size
   - Reviews given to others
   - Self-merge rate
   - Comparison to organization baseline

2. **Organization Baseline** - Context for comparison:
   - Org-wide average merge rate
   - Org-wide average merge time
   - Org-wide average PR size

3. **Individual Contributor Trends** - Weekly breakdown for top contributors showing:
   - Weekly PR activity
   - Merge rate trends
   - PR size patterns
   - Self-merge behavior
   - Trend indicators (↑ improving, → stable, ↓ declining)

4. **Repository Health Indicators** - Team dynamics analysis:
   - **Bus Factor Risk**: Are contributions too concentrated?
   - **Review Culture**: Self-merge vs. peer review rates
   - **Review Participation**: % of contributors who review others' PRs

## Usage

### Basic Usage

```bash
# Generate contributor report for a specific repo
uv run pr-metrics --org 'YourOrg' --repo 'your-repo' --days 30 --report --terminal
```

### Examples

```bash
# 90-day analysis of a mobile app repository
uv run pr-metrics --org 'YourOrg' --repo 'mobile-app' --days 90 --report --terminal

# Quick 14-day snapshot (default)
uv run pr-metrics --org 'YourOrg' --repo 'backend-api' --report --terminal

# Backend repo with 60-day history
uv run pr-metrics --org 'YourOrg' --repo 'backend-api' --days 60 --report --terminal
```

### Requirements

The contributor report requires:
- `--repo` flag to specify repository
- `--report --terminal` flags for the rich output
- Existing data collected with enhanced fields (reviews, merges, etc.)

## Metrics Explained

### Contributor-Level Metrics

| Metric | Description | Interpretation |
|--------|-------------|----------------|
| **PRs** | Total pull requests created | Higher = more active |
| **Merged** | PRs successfully merged | Should be close to total PRs |
| **Merge Rate** | % of PRs merged | 90%+ is excellent, <75% may indicate issues |
| **Avg Time** | Average time from creation to merge | <24h is fast, >72h may slow down team |
| **Avg Size** | Average lines changed per PR | Smaller PRs (< 200 lines) merge faster |
| **Reviews Given** | Number of PRs reviewed for others | Higher = better collaboration |
| **Self-Merge %** | % of own PRs merged without review | Lower is better for code quality |
| **vs Org** | Comparison to organization average | ↑ Better, → Average, ↓ Below |

### Health Indicators

#### Bus Factor Risk
- **Good** (<60%): Contributions well-distributed
- **Moderate** (60-80%): Top contributors doing majority of work
- **High Risk** (>80%): Team highly dependent on few people

#### Self-Merge Rate
- **Good** (<25%): Strong peer review culture
- **Moderate** (25-50%): Mixed practices
- **Risk** (>50%): Too many PRs merged without review

#### Review Participation
- **Active** (≥50%): Most contributors review others
- **Moderate** (25-50%): Some review participation
- **Low** (<25%): Review burden concentrated on few people

## Color Coding

The report uses colors to highlight performance:

- 🟢 **Green**: Better than org average or excellent metrics
- 🟡 **Yellow**: Average or moderate performance
- 🔴 **Red**: Below org average or concerning metrics

### Merge Rate Colors
- 🟢 Green: ≥90% (excellent)
- 🟡 Yellow: 75-90% (good)
- 🔴 Red: <75% (needs attention)

### Merge Time Colors
- 🟢 Green: <24 hours (fast)
- 🟡 Yellow: 24-72 hours (moderate)
- 🔴 Red: >72 hours (slow)

## Understanding the Output

### Sample Report Structure

```
╭─ 📊 Overview ─╮
│ Date range, contributors, total PRs
╰────────────────╯

╭─ 📏 Org Baseline ─╮
│ Organization averages for comparison
╰────────────────────╯

╭─ Contributor Rankings ─╮
│ Table showing all contributors with metrics
╰─────────────────────────╯

╭─ 👤 Individual Contributor Deep Dives ─╮
│ Weekly trends for top 5 contributors
╰──────────────────────────────────────────╯

╭─ 🏥 Health Check ─╮
│ Repository health indicators
╰────────────────────╯
```

## Best Practices

### For Team Leads

1. **Weekly Reviews**: Run weekly reports to catch trends early
   ```bash
   uv run pr-metrics --org 'YourOrg' --repo 'your-repo' --days 7 --report --terminal
   ```

2. **Monthly Deep Dives**: Monthly 30-60 day analysis for performance reviews
   ```bash
   uv run pr-metrics --org 'YourOrg' --repo 'your-repo' --days 60 --report --terminal
   ```

3. **Focus on Trends**: Look for trend arrows (↑↓→) not just absolutes
4. **Compare to Baseline**: Use "vs Org" column to identify outliers
5. **Watch Health Indicators**: Monitor bus factor and review participation

### For Contributors

1. **Track Your Progress**: Monitor your weekly trends
2. **Aim for Balance**:
   - Keep PRs small (<200 lines when possible)
   - Maintain high merge rate (>90%)
   - Participate in reviews (not just submit PRs)
3. **Review Others' Code**: Contribute to review participation metric

### For Engineering Managers

1. **Identify Bottlenecks**: High self-merge rates may indicate review capacity issues
2. **Balance Workload**: Watch bus factor - avoid over-dependence on key contributors
3. **Encourage Collaboration**: Use review participation to foster team collaboration
4. **Set Goals**: Use org baseline to set realistic team targets

## Data Requirements

### Enhanced Fields

The contributor report requires data collected with enhanced fields:
- `reviews` - Review count per PR
- `reviewers` - Who reviewed each PR
- `merged_by` - Who clicked merge
- `self_merged` - Whether author merged own PR
- `changed_files` - File count
- `comments_count` - Discussion activity
- `time_to_first_review_hours` - Review responsiveness

### Collection

To collect enhanced data:
```bash
uv run pr-metrics --org 'YourOrg' --days 30
```

Data is stored in Hive-partitioned format under `output/data/`.

## Troubleshooting

### "No contributor data available"

**Cause**: No data for the specified repository
**Solution**:
1. Check repository name spelling
2. Collect fresh data: `uv run pr-metrics --org 'YourOrg' --days 30`
3. Verify data exists: `ls output/data/org=YourOrg/repo=your-repo/`

### "Repository name required for contributor report"

**Cause**: `--repo` flag not provided
**Solution**: Add `--repo 'repository-name'` to command

### Missing review data (all zeros)

**Cause**: Old data collected before enhanced fields
**Solution**: Re-collect data to get review/merge information

## Comparing Across Time Periods

### This Month vs Last Month

```bash
# Collect data for different periods
uv run pr-metrics --org 'YourOrg' --days 30  # This month
# ... save report ...

uv run pr-metrics --org 'YourOrg' --days 60  # Last 2 months
# Compare metrics manually
```

### Tracking Improvement

Monitor these over time:
1. **Merge rate trending up?**
2. **Merge time trending down?**
3. **Review participation increasing?**
4. **Bus factor improving (more balanced)?**

## Advanced Usage

### Combining with Other Flags

```bash
# Use --min-prs to filter low-activity repos when collecting
uv run pr-metrics --org 'YourOrg' --min-prs 5

# Then analyze specific high-activity repo
uv run pr-metrics --org 'YourOrg' --repo 'high-activity-repo' --days 90 --report --terminal
```

### Automation

Create a weekly cron job:
```bash
#!/bin/bash
# weekly-pr-metrics.sh

# Collect data
uv run pr-metrics --org 'YourOrg' --days 7

# Generate reports for key repos
uv run pr-metrics --org 'YourOrg' --repo 'backend' --days 7 --report --terminal > reports/backend_$(date +%Y%m%d).txt
uv run pr-metrics --org 'YourOrg' --repo 'frontend' --days 7 --report --terminal > reports/frontend_$(date +%Y%m%d).txt
```

## Related Documentation

- [Main README](../README.md) - Getting started guide
- [Data Availability](./DATA_AVAILABILITY.md) - Technical details on collected metrics
- [Installation Guide](../INSTALL.md) - Setup instructions

## Support

For issues or feature requests, please check the project repository.
