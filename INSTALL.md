# Installation Guide

## Prerequisites

- Python 3.9 or higher
- [uv](https://docs.astral.sh/uv/) package manager
- [GitHub CLI (gh)](https://cli.github.com/) authenticated with your GitHub account

## Installation Methods

### 1. Use with `uv run` (Recommended - No Installation Needed!)

The easiest way to use this tool is with `uv run`, which automatically manages dependencies:

```bash
# Clone or navigate to the repository
cd prs-troughput

# Run directly with uv run - no installation needed!
uv run pr-metrics --help

# uv automatically creates a venv and installs dependencies on first run
uv run pr-metrics --org my-org --days 30
```

**This is the recommended approach** because:
- No manual installation or venv management required
- Dependencies are automatically handled
- Always uses the latest code from your directory
- Perfect for development and regular use

### 2. Install as a Global Tool

Install once and use the `pr-metrics` command anywhere:

```bash
# Install globally with uv
uv tool install .

# Now 'pr-metrics' is available everywhere
pr-metrics --help
pr-metrics --org my-org
```

### 3. Local Development (Editable Install)

For advanced development workflows:

```bash
# Create a venv and install in editable mode
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv pip install -e .

# Or install with dev dependencies
uv pip install -e ".[dev]"
```

## Usage

### Basic Usage

```bash
# Collect metrics for default org (last 14 days)
uv run pr-metrics

# Collect metrics for a specific organization
uv run pr-metrics --org my-org-name

# Collect metrics for the last 30 days
uv run pr-metrics --days 30

# Generate a terminal report from existing data
uv run pr-metrics --report --terminal

# Generate a markdown report
uv run pr-metrics --report
```

### Advanced Options

```bash
# Full repository scan (slower but more complete)
uv run pr-metrics --full-scan --days 30

# Filter repos by minimum PR count
uv run pr-metrics --min-prs 5

# Show top 10 contributors in weekly breakdown
uv run pr-metrics --report --terminal --top-n 10

# Set organization via environment variable
export PR_METRICS_ORG="my-org"
uv run pr-metrics
```

### Using as a Python Module

```bash
# Run as a module with uv
uv run python -m pr_metrics --help
uv run python -m pr_metrics --org my-org --days 7
```

## Configuration

### Environment Variables

- `PR_METRICS_ORG`: Default organization to analyze (can be overridden with `--org`)

Example:

```bash
export PR_METRICS_ORG="my-default-org"
pr-metrics  # Uses 'my-default-org'
pr-metrics --org another-org  # Overrides to use 'another-org'
```

## Updating

If installed as a tool:

```bash
uv tool upgrade pr-metrics
```

If installed in editable mode, just pull the latest changes:

```bash
git pull origin main
```

## Uninstalling

```bash
# If installed as a tool
uv tool uninstall pr-metrics

# If installed with pip
uv pip uninstall pr-metrics
```

## Troubleshooting

### GitHub CLI Authentication

Make sure you're authenticated with the GitHub CLI:

```bash
gh auth status
gh auth login  # If not authenticated
```

### Missing Dependencies

If you encounter import errors, ensure all dependencies are installed:

```bash
uv pip install -e .
```

### Permission Issues

For global installation, you might need appropriate permissions. Consider using a virtual environment or `uv tool install` instead.
