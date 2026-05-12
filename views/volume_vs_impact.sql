-- volume_vs_impact.sql
-- Per-author authored-commits-vs-impact metrics. Implements playbook §5.
-- Strips integration + infra_deploy + maintenance to show "real authoring" volume.
--
-- Depends on: attributed_commits table (from work_attribution_macro.sql)
-- Parameters: $min_commits (default 5)

WITH classified AS (
  SELECT *,
    primary_label IN ('integration','infra_deploy','maintenance') AS is_operational,
    primary_label IN ('feature_development','refactoring','testing','bug_fix','agent_tooling','docs') AS is_strategic
  FROM attributed_commits
)
SELECT
  author,
  COUNT(*) AS raw_commits,
  SUM(CASE WHEN is_operational THEN 1 ELSE 0 END) AS operational_commits,
  SUM(CASE WHEN is_strategic THEN 1 ELSE 0 END) AS authored_commits,
  ROUND(100.0 * SUM(CASE WHEN is_strategic THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_authored,
  ROUND(MEDIAN(CASE WHEN is_strategic THEN churn END), 0) AS median_churn_authored,
  ROUND(SUM(CASE WHEN is_strategic THEN churn ELSE 0 END), 0) AS total_churn_authored,
  ROUND(AVG(CASE WHEN is_strategic THEN changed_files END), 1) AS avg_files_authored,
  SUM(CASE WHEN is_strategic AND task_id IS NOT NULL AND task_id != '' THEN 1 ELSE 0 END) AS traced_authored,
  ROUND(100.0 * SUM(CASE WHEN is_strategic AND task_id IS NOT NULL AND task_id != '' THEN 1 ELSE 0 END)
        / NULLIF(SUM(CASE WHEN is_strategic THEN 1 ELSE 0 END), 0), 1) AS pct_traced_authored,
  -- Confidence floor — if ≥30% of authored commits are low-confidence, flag
  ROUND(100.0 * SUM(CASE WHEN is_strategic AND confidence < 0.7 THEN 1 ELSE 0 END)
        / NULLIF(SUM(CASE WHEN is_strategic THEN 1 ELSE 0 END), 0), 1) AS pct_low_confidence_authored
FROM classified
GROUP BY author
HAVING COUNT(*) >= $min_commits
ORDER BY raw_commits DESC;
