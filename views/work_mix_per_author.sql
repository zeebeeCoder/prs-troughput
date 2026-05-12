-- work_mix_per_author.sql
-- Per-author × macro-category pivot. Output shape suits a stacked horizontal bar.
--
-- Depends on: setup.sql, contributors.sql, work_attribution_macro.sql (run that to materialize attributions)
-- Parameters: $org, $repo, $days_back, $min_commits (default 5)
--
-- Workflow:
--   1. Run setup.sql + contributors.sql
--   2. CREATE TABLE attributed_commits AS <work_attribution_macro.sql>
--   3. Run this view referencing attributed_commits

SELECT
  author,
  COUNT(*) AS total_commits,
  SUM(CASE WHEN primary_label = 'feature_development' THEN 1 ELSE 0 END) AS feature_development,
  SUM(CASE WHEN primary_label = 'refactoring'         THEN 1 ELSE 0 END) AS refactoring,
  SUM(CASE WHEN primary_label = 'testing'             THEN 1 ELSE 0 END) AS testing,
  SUM(CASE WHEN primary_label = 'bug_fix'             THEN 1 ELSE 0 END) AS bug_fix,
  SUM(CASE WHEN primary_label = 'agent_tooling'       THEN 1 ELSE 0 END) AS agent_tooling,
  SUM(CASE WHEN primary_label = 'docs'                THEN 1 ELSE 0 END) AS docs,
  SUM(CASE WHEN primary_label = 'infra_deploy'        THEN 1 ELSE 0 END) AS infra_deploy,
  SUM(CASE WHEN primary_label = 'integration'         THEN 1 ELSE 0 END) AS integration,
  SUM(CASE WHEN primary_label = 'maintenance'         THEN 1 ELSE 0 END) AS maintenance,
  SUM(CASE WHEN primary_label = 'unclassified'        THEN 1 ELSE 0 END) AS unclassified,
  -- Strategic vs operational ratio (playbook §1)
  ROUND(100.0 * SUM(CASE WHEN primary_label IN
    ('feature_development','refactoring','testing','bug_fix','agent_tooling','docs')
    THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_strategic,
  ROUND(100.0 * SUM(CASE WHEN primary_label IN
    ('infra_deploy','integration','maintenance')
    THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_operational
FROM attributed_commits
GROUP BY author
HAVING COUNT(*) >= $min_commits
ORDER BY total_commits DESC;
