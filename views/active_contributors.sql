-- active_contributors.sql
-- Returns ALL contributors (not bots) with at least min_units of activity in the window.
-- Use this instead of top-N to avoid silently dropping contributors who fall below an arbitrary cut.
--
-- Depends on: setup.sql, contributors.sql
-- Parameters:
--   $org        — VARCHAR (e.g. 'Eve-World-Platform')
--   $repo       — VARCHAR (e.g. 'coto-joy'); pass '*' for all repos
--   $days_back  — INTEGER (e.g. 90)
--   $min_units  — INTEGER (default 5)

WITH commit_activity AS (
  SELECT
    cr.author_canonical,
    COUNT(DISTINCT cr.sha) AS commits
  FROM contributors_resolved cr
  WHERE cr.org = $org
    AND ($repo = '*' OR cr.repo = $repo)
    AND cr.authored_at >= now() - INTERVAL ($days_back || ' day')
    AND cr.author_canonical IS NOT NULL
    AND cr.author_canonical NOT LIKE 'bot:%'
  GROUP BY cr.author_canonical
),
pr_activity AS (
  SELECT
    p.author AS author_canonical,  -- PR author is GitHub login; identity layer doesn't merge yet
    COUNT(*) AS prs_created
  FROM prs_latest p
  WHERE p.org = $org
    AND ($repo = '*' OR p.repo = $repo)
    AND p.created_at >= now() - INTERVAL ($days_back || ' day')
  GROUP BY p.author
)
SELECT
  COALESCE(c.author_canonical, p.author_canonical) AS author,
  COALESCE(c.commits, 0) AS commits,
  COALESCE(p.prs_created, 0) AS prs_created,
  COALESCE(c.commits, 0) + COALESCE(p.prs_created, 0) AS total_units
FROM commit_activity c
FULL OUTER JOIN pr_activity p USING (author_canonical)
WHERE COALESCE(c.commits, 0) + COALESCE(p.prs_created, 0) >= $min_units
ORDER BY total_units DESC;
