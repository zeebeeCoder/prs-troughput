-- invisible_wip_with_owner.sql
-- Branches ahead of master with no open PR + the head-commit author + idle days.
-- Surfaces hidden inventory (playbook §4).
--
-- Depends on: setup.sql, contributors.sql
-- Parameters: $org, $repo

SELECT
  b.branch,
  b.head_sha,
  cr.author_canonical AS head_author,
  c.subject AS head_subject,
  b.ahead_main,
  b.behind_main,
  b.last_commit_at,
  date_diff('day', b.last_commit_at, now()) AS idle_days,
  b.task_id,
  -- concern bands per playbook §4
  CASE
    WHEN b.ahead_main >= 50 AND date_diff('day', b.last_commit_at, now()) >= 14 THEN 'high'
    WHEN b.ahead_main >= 10 AND date_diff('day', b.last_commit_at, now()) >= 30 THEN 'medium'
    WHEN b.task_id IS NOT NULL AND date_diff('day', b.last_commit_at, now()) >= 7 THEN 'flag_ticket_stalled'
    ELSE 'low'
  END AS concern,
  b.pr_url
FROM branches_latest b
LEFT JOIN commits_latest c ON b.head_sha = c.sha
LEFT JOIN contributors_resolved cr ON b.head_sha = cr.sha
WHERE b.org = $org AND b.repo = $repo
  AND COALESCE(b.has_open_pr, false) = false
  AND COALESCE(b.ahead_main, 0) > 0
  AND b.branch NOT IN ('master', 'main', 'develop')
ORDER BY
  CASE
    WHEN b.ahead_main >= 50 AND date_diff('day', b.last_commit_at, now()) >= 14 THEN 1
    WHEN b.ahead_main >= 10 AND date_diff('day', b.last_commit_at, now()) >= 30 THEN 2
    ELSE 3
  END,
  b.ahead_main DESC;
