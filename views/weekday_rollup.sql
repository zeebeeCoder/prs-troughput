-- weekday_rollup.sql
-- Per-author weekday distribution (hour collapsed). For at-a-glance "who works which days".
--
-- Depends on: setup.sql, contributors.sql
-- Parameters: $org, $repo, $days_back

SELECT
  cr.author_canonical AS author,
  CASE ((strftime(c.authored_at, '%w')::INTEGER + 6) % 7)
    WHEN 0 THEN 'Mon' WHEN 1 THEN 'Tue' WHEN 2 THEN 'Wed' WHEN 3 THEN 'Thu'
    WHEN 4 THEN 'Fri' WHEN 5 THEN 'Sat' WHEN 6 THEN 'Sun'
  END AS weekday,
  ((strftime(c.authored_at, '%w')::INTEGER + 6) % 7) AS weekday_idx,
  COUNT(*) AS commits,
  SUM(c.additions + c.deletions) AS churn
FROM commits_latest c
JOIN contributors_resolved cr USING (sha)
WHERE c.org = $org AND c.repo = $repo
  AND c.authored_at >= now() - INTERVAL ($days_back || ' day')
  AND cr.author_canonical NOT LIKE 'bot:%'
GROUP BY author, weekday, weekday_idx
ORDER BY author, weekday_idx;
