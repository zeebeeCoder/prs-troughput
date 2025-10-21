# Latest Changes - Contributor Performance Metrics

## 🎉 Major Feature: Contributor Performance Reports

Added comprehensive contributor-focused reporting when using the `--repo` flag.

### New Features

**1. Repository-Scoped Analysis**
- New `--repo` CLI flag to focus analysis on a single repository
- Automatically triggers contributor performance report mode
- Enhanced data collection with review and merge tracking

**2. Contributor Performance Metrics**
- Individual contributor rankings with:
  - PR count (created vs merged)
  - Merge rate percentage
  - Average merge time
  - Average PR size
  - Reviews given to others
  - Self-merge rate
- Organization baseline comparison (↑ Better, → Average, ↓ Below)
- Weekly trend analysis per contributor with trend indicators

**3. Repository Health Indicators**
- **Bus Factor Risk** - Contribution concentration assessment
- **Review Culture** - Self-merge vs peer-review analysis
- **Review Participation** - Team collaboration metrics

**4. Enhanced Data Collection**
- `reviews` - Count of reviews per PR
- `reviewers` - Comma-separated list of reviewer logins
- `merged_by` - User who clicked the merge button
- `self_merged` - Boolean flag for self-merged PRs
- `changed_files` - Number of files modified
- `comments_count` - Discussion activity
- `time_to_first_review_hours` - Review responsiveness metric

### Technical Improvements

**1. DuckDB with Hive Partitioning**
- Replaced single Parquet files with Hive-partitioned structure
- Data organized by: `org=X/repo=Y/year=YYYY/month=MM/`
- Schema evolution support with `union_by_name=true`
- Efficient filtering and time-based queries

**2. Defensive SQL Queries**
- All queries check schema before execution using `DESCRIBE`
- Gracefully handles missing columns from older data
- Backwards compatible with data collected before enhancements

**3. Bug Fixes**
- Fixed DuckDB UNNEST syntax for reviewer aggregation queries
- Added schema mismatch handling for mixed data collection periods
- Proper CROSS JOIN syntax for array expansion queries

### Documentation

**Added:**
- `docs/CONTRIBUTOR_METRICS.md` - Complete guide to contributor reporting
- `docs/DATA_AVAILABILITY.md` - Technical reference for available GitHub fields

**Updated:**
- README.md - Added contributor reports section, enhanced use cases
- All examples use generic organization names (removed business-specific refs)

### Code Changes

**Modified Files:**
- `src/pr_metrics/cli.py` - Added --repo flag, routing to contributor report
- `src/pr_metrics/github.py` - Enhanced data collection fields
- `src/pr_metrics/processor.py` - Added helper functions for review/merge data extraction
- `src/pr_metrics/queries.py` - Added 4 new query functions with defensive column checking
- `src/pr_metrics/reports.py` - Added generate_contributor_report() function
- `src/pr_metrics/storage.py` - Migrated to Hive partitioning with union_by_name
- `src/pr_metrics/utils.py` - Removed hardcoded org, require explicit specification

## 🧹 Repository Cleanup

**Removed:**
- All hardcoded organization references from code
- Business-specific examples from documentation
- Output files with real organizational data

**Security:**
- No default organization (prevents accidental data exposure)
- Clear error messages guide users to configure org via CLI or env var
- `.gitignore` properly excludes all output data

## 📊 Use Cases Expanded

Now supports:
- Performance reviews and 1-on-1s
- Team capacity planning
- Sprint retrospectives with trend analysis
- Bottleneck identification
- Risk management (bus factor monitoring)
- Review culture assessment
- Individual growth tracking

## Migration Notes

**For Existing Users:**
- Set `PR_METRICS_ORG` environment variable or use `--org` flag (required now)
- Old data in `output/*.parquet` files still works (legacy fallback)
- New data stored in `output/data/` with Hive partitioning
- Re-collect data to get enhanced review metrics for historical periods

**Data Collection:**
- Run collection: `uv run pr-metrics --org YourOrg --days 30`
- Generate org report: `uv run pr-metrics --org YourOrg --report --terminal`
- Generate repo report: `uv run pr-metrics --org YourOrg --repo RepoName --days 60 --report --terminal`

## Verification

All features tested and verified:
- ✅ Schema mismatch handling works correctly
- ✅ Review data collection accurate (verified against GitHub API)
- ✅ Contributor rankings match actual PR data
- ✅ Health indicators calculate correctly
- ✅ No business-specific references in codebase
- ✅ Generic examples throughout documentation
