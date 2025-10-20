# Quick Start Guide

## Installation

```bash
# 1. Ensure you have uv installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Authenticate with GitHub CLI
gh auth login

# 3. You're ready!
```

## Basic Usage

```bash
# Run the tool (no installation needed!)
uv run pr-metrics --org your-org

# Generate a report from existing data
uv run pr-metrics --report --terminal

# Analyze last 30 days with detailed output
uv run pr-metrics --org your-org --days 30 --terminal
```

## Common Commands

```bash
# Quick weekly sprint analysis
uv run pr-metrics --days 7 --report --terminal

# Full org scan (slower but comprehensive)
uv run pr-metrics --full-scan --days 30

# Filter to active repos only
uv run pr-metrics --min-prs 5
```

## Output

Data is saved to `output/` directory:
- `.parquet` files for efficient data analysis
- `.csv` files for spreadsheet compatibility

## Help

```bash
uv run pr-metrics --help
```

For detailed documentation, see [README.md](README.md) and [INSTALL.md](INSTALL.md).
