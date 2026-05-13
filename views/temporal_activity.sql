-- temporal_activity.sql
-- Normalized temporal grain for heatmaps and timeline charts.
--
-- Purpose: one row per observable delivery unit (commit, PR, branch snapshot)
-- with common actor/category/time dimensions, contribution-signal flags, and
-- numeric impact measures.
--
-- Expected lens: velocity / quality / lifecycle visualization.
-- Depends on: setup.sql, contributors.sql, and an `attributed_commits` table
-- created from work_attribution_macro.sql for commit macro categories.
-- Parameters:
--   $org        — VARCHAR (e.g. 'Eve-World-Platform')
--   $repo       — VARCHAR (e.g. 'coto-joy'); pass '*' for all repos in the org
--   $days_back  — INTEGER (e.g. 90)

WITH file_flags AS (
  SELECT
    org,
    repo,
    sha,
    COUNT(*) AS file_rows,
    SUM(COALESCE(additions, 0) + COALESCE(deletions, 0)) AS file_churn,
    SUM(CASE WHEN is_test THEN 1 ELSE 0 END) AS test_files,
    SUM(CASE WHEN is_sensitive THEN 1 ELSE 0 END) AS sensitive_files,
    SUM(CASE WHEN is_generated THEN 1 ELSE 0 END) AS generated_files
  FROM commit_files
  GROUP BY 1, 2, 3
),
delivery_by_sha AS (
  SELECT
    org,
    repo,
    delivery_sha AS sha,
    arg_max(delivery_mode, delivered_at) AS delivery_mode,
    arg_max(pr_number, delivered_at) AS pr_number,
    COUNT(*) AS delivery_events,
    MAX(delivered_at) AS delivered_at
  FROM delivery_events_latest
  GROUP BY 1, 2, 3
),
semantic_flags AS (
  SELECT
    org,
    repo,
    unit_kind,
    unit_id,
    MAX(CASE WHEN category_namespace = 'quality' AND category = 'test_coverage' THEN 1 ELSE 0 END) AS has_test_coverage,
    MAX(CASE WHEN category_namespace = 'quality' AND category = 'sensitive_path' THEN 1 ELSE 0 END) AS has_sensitive_path,
    MAX(CASE WHEN category_namespace = 'quality' AND category = 'generated_code' THEN 1 ELSE 0 END) AS has_generated_code,
    MAX(CASE WHEN category_namespace = 'work_type' AND category = 'agent_tooling' THEN 1 ELSE 0 END) AS has_agent_tooling,
    MAX(CASE WHEN category_namespace = 'quality' AND category = 'refactoring' THEN 1 ELSE 0 END) AS has_refactoring,
    string_agg(DISTINCT category, ',') FILTER (WHERE category_namespace = 'component') AS components
  FROM semantic_categories_latest
  GROUP BY 1, 2, 3, 4
),
commit_enriched AS (
  SELECT
    c.org,
    c.repo,
    'commit' AS unit_kind,
    c.sha AS unit_id,
    c.authored_at AS observed_at,
    COALESCE(cr.author_canonical, NULLIF(c.author_name, ''), 'unknown') AS actor,
    COALESCE(a.primary_label, NULLIF(c.activity_class, ''), 'unclassified') AS category,
    1 AS units,
    COALESCE(c.additions, 0) + COALESCE(c.deletions, 0) AS churn,
    COALESCE(c.changed_files, 0) AS changed_files,
    CASE WHEN COALESCE(a.primary_label, '') IN ('feature_development','refactoring','testing','bug_fix','agent_tooling','docs') THEN 1 ELSE 0 END AS strategic_units,
    CASE WHEN COALESCE(a.primary_label, '') IN ('integration','infra_deploy','maintenance') THEN 1 ELSE 0 END AS operational_units,
    CASE WHEN c.task_id IS NOT NULL OR c.spec_name IS NOT NULL THEN 1 ELSE 0 END AS traced_units,
    CASE WHEN c.task_id IS NULL AND c.spec_name IS NULL THEN 1 ELSE 0 END AS untraced_units,
    CASE WHEN c.task_id IS NULL AND c.spec_name IS NULL THEN COALESCE(c.additions, 0) + COALESCE(c.deletions, 0) ELSE 0 END AS untraced_churn,
    CASE WHEN COALESCE(c.is_direct_main, false) THEN 1 ELSE 0 END AS direct_main_units,
    CASE WHEN d.delivery_mode = 'direct_main_candidate' THEN 1 ELSE 0 END AS direct_main_delivery_units,
    CASE WHEN c.pr_number IS NOT NULL OR d.pr_number IS NOT NULL OR d.delivery_mode = 'squash' THEN 1 ELSE 0 END AS pr_linked_units,
    CASE WHEN COALESCE(f.test_files, 0) > 0 OR COALESCE(s.has_test_coverage, 0) > 0 THEN 1 ELSE 0 END AS test_coverage_units,
    CASE WHEN COALESCE(f.sensitive_files, 0) > 0 OR COALESCE(s.has_sensitive_path, 0) > 0 THEN 1 ELSE 0 END AS sensitive_units,
    CASE WHEN COALESCE(f.generated_files, 0) > 0 OR COALESCE(s.has_generated_code, 0) > 0 THEN 1 ELSE 0 END AS generated_units,
    CASE WHEN COALESCE(a.confidence, 1.0) < 0.7 THEN 1 ELSE 0 END AS low_confidence_units,
    (
      CASE WHEN COALESCE(c.additions, 0) + COALESCE(c.deletions, 0) >= 1000 THEN 2 ELSE 0 END +
      CASE WHEN COALESCE(c.changed_files, 0) >= 20 THEN 1 ELSE 0 END +
      CASE WHEN COALESCE(f.sensitive_files, 0) > 0 OR COALESCE(s.has_sensitive_path, 0) > 0 THEN 2 ELSE 0 END +
      CASE
        WHEN COALESCE(f.test_files, 0) = 0
         AND COALESCE(s.has_test_coverage, 0) = 0
         AND COALESCE(a.primary_label, '') IN ('feature_development','bug_fix')
        THEN 1 ELSE 0
      END
    ) AS risk_score,
    0 AS branch_ahead,
    NULL::BIGINT AS branch_idle_days,
    a.confidence AS attribution_confidence,
    a.signal_winner,
    d.delivery_mode,
    s.components,
    c.task_id,
    c.spec_name
  FROM commits_latest c
  LEFT JOIN contributors_resolved cr
    ON cr.sha = c.sha
   AND cr.org = c.org
   AND cr.repo = c.repo
  LEFT JOIN attributed_commits a ON a.sha = c.sha
  LEFT JOIN file_flags f
    ON f.org = c.org
   AND f.repo = c.repo
   AND f.sha = c.sha
  LEFT JOIN delivery_by_sha d
    ON d.org = c.org
   AND d.repo = c.repo
   AND d.sha = c.sha
  LEFT JOIN semantic_flags s
    ON s.org = c.org
   AND s.repo = c.repo
   AND s.unit_kind = 'commit'
   AND s.unit_id = c.sha
  WHERE c.authored_at IS NOT NULL
),
commit_units AS (
  SELECT
    org, repo, unit_kind, unit_id, observed_at, actor, category, units, churn, changed_files,
    strategic_units, operational_units, traced_units, untraced_units, untraced_churn,
    direct_main_units, direct_main_delivery_units, pr_linked_units,
    test_coverage_units, sensitive_units, generated_units, low_confidence_units,
    risk_score, CASE WHEN risk_score >= 3 THEN 1 ELSE 0 END AS risky_units,
    branch_ahead, branch_idle_days, attribution_confidence, signal_winner, delivery_mode,
    components, task_id, spec_name
  FROM commit_enriched
),
pr_enriched AS (
  SELECT
    p.org,
    p.repo,
    'pr' AS unit_kind,
    CAST(p.pr_number AS VARCHAR) AS unit_id,
    p.created_at AS observed_at,
    COALESCE(NULLIF(p.author, ''), 'unknown') AS actor,
    'pr_' || LOWER(COALESCE(NULLIF(p.state, ''), 'unknown')) AS category,
    1 AS units,
    COALESCE(p.additions, 0) + COALESCE(p.deletions, 0) AS churn,
    COALESCE(p.changed_files, 0) AS changed_files,
    0 AS strategic_units,
    0 AS operational_units,
    CASE WHEN p.task_id IS NOT NULL OR p.spec_name IS NOT NULL THEN 1 ELSE 0 END AS traced_units,
    CASE WHEN p.task_id IS NULL AND p.spec_name IS NULL THEN 1 ELSE 0 END AS untraced_units,
    CASE WHEN p.task_id IS NULL AND p.spec_name IS NULL THEN COALESCE(p.additions, 0) + COALESCE(p.deletions, 0) ELSE 0 END AS untraced_churn,
    0 AS direct_main_units,
    0 AS direct_main_delivery_units,
    1 AS pr_linked_units,
    COALESCE(s.has_test_coverage, 0) AS test_coverage_units,
    COALESCE(s.has_sensitive_path, 0) AS sensitive_units,
    COALESCE(s.has_generated_code, 0) AS generated_units,
    0 AS low_confidence_units,
    (
      CASE WHEN COALESCE(p.additions, 0) + COALESCE(p.deletions, 0) >= 1000 THEN 2 ELSE 0 END +
      CASE WHEN COALESCE(p.changed_files, 0) >= 20 THEN 1 ELSE 0 END +
      CASE WHEN COALESCE(p.checks_failed_count, 0) > 0 THEN 1 ELSE 0 END +
      CASE WHEN COALESCE(p.changes_requested_count, 0) > 0 THEN 1 ELSE 0 END
    ) AS risk_score,
    0 AS branch_ahead,
    NULL::BIGINT AS branch_idle_days,
    NULL::DOUBLE AS attribution_confidence,
    NULL AS signal_winner,
    NULL AS delivery_mode,
    s.components,
    p.task_id,
    p.spec_name
  FROM prs_latest p
  LEFT JOIN semantic_flags s
    ON s.org = p.org
   AND s.repo = p.repo
   AND s.unit_kind = 'pr'
   AND s.unit_id = CAST(p.pr_number AS VARCHAR)
  WHERE p.created_at IS NOT NULL
),
pr_units AS (
  SELECT
    org, repo, unit_kind, unit_id, observed_at, actor, category, units, churn, changed_files,
    strategic_units, operational_units, traced_units, untraced_units, untraced_churn,
    direct_main_units, direct_main_delivery_units, pr_linked_units,
    test_coverage_units, sensitive_units, generated_units, low_confidence_units,
    risk_score, CASE WHEN risk_score >= 3 THEN 1 ELSE 0 END AS risky_units,
    branch_ahead, branch_idle_days, attribution_confidence, signal_winner, delivery_mode,
    components, task_id, spec_name
  FROM pr_enriched
),
branch_enriched AS (
  SELECT
    b.org,
    b.repo,
    'branch' AS unit_kind,
    b.branch AS unit_id,
    b.last_commit_at AS observed_at,
    COALESCE(cr.author_canonical, NULLIF(b.last_author, ''), 'unknown') AS actor,
    CASE
      WHEN b.branch IN ('main', 'master', 'develop') THEN 'branch_baseline'
      WHEN COALESCE(b.has_open_pr, false) THEN 'branch_with_open_pr'
      WHEN COALESCE(b.ahead_main, 0) > 0 THEN 'invisible_wip'
      ELSE 'branch_snapshot'
    END AS category,
    1 AS units,
    COALESCE(b.ahead_main, 0) AS churn,
    0 AS changed_files,
    0 AS strategic_units,
    CASE WHEN b.branch IN ('main', 'master', 'develop') THEN 1 ELSE 0 END AS operational_units,
    CASE WHEN b.task_id IS NOT NULL OR b.spec_name IS NOT NULL THEN 1 ELSE 0 END AS traced_units,
    CASE WHEN b.task_id IS NULL AND b.spec_name IS NULL THEN 1 ELSE 0 END AS untraced_units,
    CASE WHEN b.task_id IS NULL AND b.spec_name IS NULL THEN COALESCE(b.ahead_main, 0) ELSE 0 END AS untraced_churn,
    0 AS direct_main_units,
    0 AS direct_main_delivery_units,
    CASE WHEN COALESCE(b.has_open_pr, false) THEN 1 ELSE 0 END AS pr_linked_units,
    COALESCE(s.has_test_coverage, 0) AS test_coverage_units,
    COALESCE(s.has_sensitive_path, 0) AS sensitive_units,
    COALESCE(s.has_generated_code, 0) AS generated_units,
    0 AS low_confidence_units,
    CASE
      WHEN COALESCE(b.ahead_main, 0) >= 50 AND date_diff('day', b.last_commit_at, now()) >= 14 THEN 3
      WHEN COALESCE(b.ahead_main, 0) >= 10 AND date_diff('day', b.last_commit_at, now()) >= 30 THEN 2
      WHEN b.task_id IS NOT NULL AND date_diff('day', b.last_commit_at, now()) >= 7 THEN 1
      ELSE 0
    END AS risk_score,
    COALESCE(b.ahead_main, 0) AS branch_ahead,
    date_diff('day', b.last_commit_at, now()) AS branch_idle_days,
    NULL::DOUBLE AS attribution_confidence,
    NULL AS signal_winner,
    NULL AS delivery_mode,
    s.components,
    b.task_id,
    b.spec_name
  FROM branches_latest b
  LEFT JOIN contributors_resolved cr
    ON cr.sha = b.head_sha
   AND cr.org = b.org
   AND cr.repo = b.repo
  LEFT JOIN semantic_flags s
    ON s.org = b.org
   AND s.repo = b.repo
   AND s.unit_kind = 'branch'
   AND s.unit_id = b.branch
  WHERE b.last_commit_at IS NOT NULL
),
branch_units AS (
  SELECT
    org, repo, unit_kind, unit_id, observed_at, actor, category, units, churn, changed_files,
    strategic_units, operational_units, traced_units, untraced_units, untraced_churn,
    direct_main_units, direct_main_delivery_units, pr_linked_units,
    test_coverage_units, sensitive_units, generated_units, low_confidence_units,
    risk_score, CASE WHEN risk_score >= 3 THEN 1 ELSE 0 END AS risky_units,
    branch_ahead, branch_idle_days, attribution_confidence, signal_winner, delivery_mode,
    components, task_id, spec_name
  FROM branch_enriched
),
units AS (
  SELECT * FROM commit_units
  UNION ALL
  SELECT * FROM pr_units
  UNION ALL
  SELECT * FROM branch_units
)
SELECT
  org,
  repo,
  unit_kind,
  unit_id,
  observed_at,
  CAST(observed_at AS DATE) AS activity_date,
  CAST(date_trunc('week', observed_at) AS DATE) AS week_start,
  CAST(date_trunc('month', observed_at) AS DATE) AS month_start,
  ((strftime(observed_at, '%w')::INTEGER + 6) % 7) AS weekday_idx,
  CASE ((strftime(observed_at, '%w')::INTEGER + 6) % 7)
    WHEN 0 THEN 'Mon' WHEN 1 THEN 'Tue' WHEN 2 THEN 'Wed' WHEN 3 THEN 'Thu'
    WHEN 4 THEN 'Fri' WHEN 5 THEN 'Sat' WHEN 6 THEN 'Sun'
  END AS weekday_label,
  strftime(observed_at, '%H')::INTEGER AS hour_of_day,
  actor,
  category,
  units,
  churn,
  changed_files,
  strategic_units,
  operational_units,
  traced_units,
  untraced_units,
  untraced_churn,
  direct_main_units,
  direct_main_delivery_units,
  pr_linked_units,
  test_coverage_units,
  sensitive_units,
  generated_units,
  low_confidence_units,
  risk_score,
  risky_units,
  branch_ahead,
  branch_idle_days,
  attribution_confidence,
  signal_winner,
  delivery_mode,
  components,
  task_id,
  spec_name
FROM units
WHERE org = $org
  AND ($repo = '*' OR repo = $repo)
  AND observed_at >= now() - INTERVAL ($days_back || ' day')
ORDER BY observed_at, repo, unit_kind, actor;
