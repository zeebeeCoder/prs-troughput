# Data Availability Analysis for Contributor Performance Feature

## ✅ Data Currently Available from GitHub CLI

### Per-PR Metrics (Already Collected)
- ✅ `number` - PR identifier
- ✅ `author` - PR creator {id, login, name, is_bot}
- ✅ `createdAt` - PR creation timestamp
- ✅ `mergedAt` - Merge timestamp
- ✅ `closedAt` - Close timestamp
- ✅ `additions` - Lines added
- ✅ `deletions` - Lines deleted
- ✅ `isDraft` - Draft status
- ✅ `labels` - PR labels array
- ✅ `reviewDecision` - Overall review status (APPROVED, REVIEW_REQUIRED, etc.)

### Per-PR Metrics (Available but NOT Currently Collected)
- ✅ `commits` - Full commit history with:
  - `authoredDate` / `committedDate`
  - `authors[]` - Array of commit authors (supports co-authors)
  - `messageHeadline` / `messageBody`
  - `oid` - Commit hash

- ✅ `reviews` - Complete review history:
  - `author` {login, name}
  - `authorAssociation` (MEMBER, CONTRIBUTOR, etc.)
  - `body` - Review comment text
  - `submittedAt` - Review timestamp
  - `state` - APPROVED, CHANGES_REQUESTED, COMMENTED
  - `commit` {oid} - Which commit was reviewed

- ✅ `latestReviews` - Most recent review per reviewer

- ✅ `reviewRequests` - Pending review requests:
  - `login` - Requested reviewer username

- ✅ `mergedBy` - Who clicked merge:
  - `id`, `login`, `name`, `is_bot`

- ✅ `comments` - PR discussion comments (not inline code reviews):
  - `author` {login}
  - `body` - Comment text
  - `createdAt` - Comment timestamp
  - `url` - Link to comment

- ✅ `changedFiles` - Number of files modified (int)

### Additional Available Fields (Lower Priority)
- ✅ `assignees` - PR assignees
- ✅ `milestone` - Associated milestone
- ✅ `updatedAt` - Last update timestamp
- ✅ `state` - open/closed/merged
- ✅ `title` - PR title
- ✅ `body` - PR description
- ✅ `url` - PR URL
- ✅ `statusCheckRollup` - CI/CD status
- ✅ `baseRefName` / `headRefName` - Branch names

## 📊 Metrics We Can Calculate

### Individual Contributor Metrics

#### Throughput & Velocity
- **PRs created** - Count PRs where `author.login = contributor`
- **PRs merged** - Count where `mergedAt != null`
- **Merge rate** - `merged / total * 100%`
- **Average time to merge** - `avg(mergedAt - createdAt)`
- **Submission frequency** - PRs per week/month

#### Code Quality & Size
- **Average PR size** - `avg(additions + deletions)`
- **Lines changed distribution** - Small/Medium/Large buckets
- **Files changed per PR** - `avg(changedFiles)`
- **Commits per PR** - `len(commits)`

#### Collaboration & Review Activity
- **PRs reviewed for others** - Count `reviews[]` where `reviews.author.login = contributor`
- **Reviews given** - Total review count
- **Approval rate** - `reviews[state=APPROVED] / total reviews * 100%`
- **Average review turnaround** - `avg(review.submittedAt - pr.createdAt)` for PRs reviewed by contributor
- **Comments made** - Count `comments[]` where `author.login = contributor`

#### Review Reception (As Author)
- **Time to first review** - `min(reviews.submittedAt) - createdAt`
- **Reviews received per PR** - `avg(len(reviews))`
- **Approval rate received** - `PRs with reviewDecision=APPROVED / total`
- **Requested reviewers response rate** - How often reviewRequests result in actual reviews

#### Advanced Metrics
- **Self-merge rate** - `count(mergedBy.login = author.login) / merged PRs`
- **Co-authorship rate** - PRs with multiple commit authors
- **Draft usage** - `count(isDraft=true) / total`
- **Revision cycles** - Count commits after first review

### Repository-Level Metrics (For Comparison)
- **Contributor count** - Unique `author.login` values
- **Review participation** - % of contributors who review others' PRs
- **Average team response time** - Time to first review (org-wide)
- **Contribution balance** - Distribution of PRs across contributors
- **Bus factor** - Concentration of contributions (e.g., top 20% of contributors = X% of PRs)

## 🎯 Recommended Implementation Strategy

### Phase 1: Enhanced Data Collection
Update `github.py:get_repo_prs()` to include:
```python
--json number,author,title,createdAt,mergedAt,closedAt,state,additions,deletions,isDraft,labels,reviewDecision,commits,reviews,reviewRequests,mergedBy,comments,changedFiles
```

### Phase 2: New Processor Functions
Add to `processor.py`:
- `extract_commits_count(pr)` - Count commits
- `extract_reviews_data(pr)` - Parse review history
- `calculate_time_to_first_review(pr)` - First review time
- `extract_reviewers(pr)` - List of reviewer logins
- `extract_merge_author(pr)` - Who merged

### Phase 3: Extended Data Model
Add columns to DuckDB schema:
```python
'commits_count': int
'reviews_count': int
'reviewers': str  # Comma-separated logins
'time_to_first_review_hours': float
'merged_by': str
'changed_files': int
'comments_count': int
'self_merged': bool
```

### Phase 4: New Queries
Add to `queries.py`:
- `get_contributor_stats_for_repo(org, repo)` - Per-user metrics in a repo
- `get_contributor_review_activity(org, repo, author)` - Reviews given by user
- `get_contributor_timeline(org, repo, author)` - Weekly activity trend
- `get_review_responsiveness(org, repo)` - Review turnaround times

## ⚠️ Considerations

### Data Collection Impact
- Fetching `reviews` and `commits` will increase API response size ~3-5x
- May need to reduce `--limit` from 200 to 100 PRs per repo to avoid timeouts
- Recommend caching/incremental updates for large repos

### Privacy & Sensitivity
- Review data includes individual performance metrics
- Consider anonymization options for broader reports
- Distinguish between constructive reviews vs. gatekeeping

### Rate Limiting
- `gh` CLI respects GitHub API rate limits (5000/hour authenticated)
- Current implementation is sequential; parallelization would help but increase rate limit pressure

## 📝 Example Data Structures

### Commits Array
```json
"commits": [
  {
    "authoredDate": "2025-10-15T08:07:32Z",
    "authors": [
      {"email": "user@example.com", "login": "username", "name": "User Name"}
    ],
    "committedDate": "2025-10-15T09:06:39Z",
    "messageHeadline": "feat: Add new feature",
    "oid": "ba95f4d69340ddcffd30958cfbdc4b78cef78223"
  }
]
```

### Reviews Array
```json
"reviews": [
  {
    "author": {"login": "reviewer1"},
    "authorAssociation": "MEMBER",
    "body": "LGTM",
    "submittedAt": "2025-10-15T08:50:06Z",
    "state": "APPROVED",
    "commit": {"oid": "f5f514800636a74f2d9cb0a8f03334da918bd443"}
  }
]
```

### MergedBy Object
```json
"mergedBy": {
  "id": "U_kgDOBnTYEQ",
  "is_bot": false,
  "login": "merger_username",
  "name": "Merger Name"
}
```

## ✅ Conclusion

**All data needed for the contributor performance feature is available via GitHub CLI!**

No additional API integration required. We can implement the full scope filter feature with:
1. Update data collection (add fields to `--json` flag)
2. Enhance processing (extract new metrics)
3. Extend data model (add columns)
4. Create new queries (contributor-focused analytics)
5. Build new reports (repo-scoped views)

The main trade-off is **increased data volume** (~3-5x larger responses), but this is manageable with smart pagination and caching.
