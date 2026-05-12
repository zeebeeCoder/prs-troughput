-- off_hours_work.sql
-- Per-author per-week % of commits authored outside business hours.
-- Burnout signal — interpret per playbook §6.
--
-- Definition of "off-hours" (author-local time):
--   - weekend (Sat or Sun)
--   - weekday before 8:00
--   - weekday after 19:00
--
-- Depends on: setup.sql, contributors.sql
-- Parameters: $org, $repo, $days_back

WITH tagged AS (
  SELECT
    cr.author_canonical AS author,
    date_trunc('week', c.authored_at) AS week,
    CASE
      WHEN strftime(c.authored_at, '%w')::INTEGER IN (0, 6) THEN 'weekend'
      WHEN strftime(c.authored_at, '%H')::INTEGER < 8 THEN 'early'
      WHEN strftime(c.authored_at, '%H')::INTEGER >= 19 THEN 'late'
      ELSE 'business'
    END AS time_band
  FROM commits_latest c
  JOIN contributors_resolved cr USING (sha)
  WHERE c.org = $org AND c.repo = $repo
    AND c.authored_at >= now() - INTERVAL ($days_back || ' day')
    AND cr.author_canonical NOT LIKE 'bot:%'
)
SELECT
  week,
  author,
  COUNT(*) AS total_commits,
  SUM(CASE WHEN time_band = 'business' THEN 1 ELSE 0 END) AS business_hours,
  SUM(CASE WHEN time_band = 'weekend'  THEN 1 ELSE 0 END) AS weekend,
  SUM(CASE WHEN time_band = 'early'    THEN 1 ELSE 0 END) AS early,
  SUM(CASE WHEN time_band = 'late'     THEN 1 ELSE 0 END) AS late,
  ROUND(100.0 * SUM(CASE WHEN time_band != 'business' THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_off_hours
FROM tagged
GROUP BY week, author
HAVING COUNT(*) >= 3   -- ignore weeks with too few commits to be meaningful
ORDER BY week DESC, pct_off_hours DESC;
