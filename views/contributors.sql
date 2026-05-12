-- contributors.sql
-- Canonical author identity normalization. Run AFTER setup.sql, BEFORE any per-author analysis.
--
-- Materializes a `contributors` view that resolves git-author identity collisions.
--
-- Strategy: cluster by author_email when present (most stable), fall back to lower-cased name.
-- Manual overrides for known same-person collisions are listed at the top — extend per repo.
--
-- The output view has columns:
--   author_canonical  — the display name to use in all reports
--   author_email      — preferred email when known
--   raw_names         — comma-separated list of original author_name values that map here
--
-- This view is referenced by every analysis view that groups by author.
-- DO NOT inline CASE WHEN identity logic in other queries — extend this file.

-- ---------- Manual overrides (extend per repo as new collisions surface) ----------
CREATE OR REPLACE VIEW _identity_overrides(raw_name_lower, canonical) AS
VALUES
  -- coto-joy known collisions:
  ('zeebee',          'Zeebee'),
  ('zeebee siwiec',   'Zeebee'),
  ('zeebeecoder',     'Zeebee'),
  ('rey',             'reyuuji28'),
  ('reyuuji28',       'reyuuji28'),
  ('barath kumar ravi', 'barathkumarravi'),
  ('barathkumarravi', 'barathkumarravi'),
  -- bots / automation (kept separate so they're filterable):
  ('github action',   'bot:github-action'),
  ('github-actions[bot]', 'bot:github-actions');

-- ---------- Per-sha author resolution ----------
CREATE OR REPLACE VIEW contributors_resolved AS
SELECT
  c.sha,
  c.org, c.repo,
  c.author_name AS raw_name,
  c.author_email,
  COALESCE(
    o.canonical,                           -- manual override hit
    NULLIF(c.author_name, '')              -- otherwise keep original
  ) AS author_canonical,
  c.authored_at
FROM commits_latest c
LEFT JOIN _identity_overrides o
  ON lower(c.author_name) = o.raw_name_lower;

-- ---------- Aggregated contributors view ----------
CREATE OR REPLACE VIEW contributors AS
SELECT
  author_canonical,
  any_value(author_email) AS author_email,
  list(DISTINCT raw_name) AS raw_names,
  COUNT(DISTINCT sha) AS lifetime_commits,
  MIN(authored_at) AS first_commit_at,
  MAX(authored_at) AS last_commit_at,
  list(DISTINCT org || '/' || repo) AS repos
FROM contributors_resolved
WHERE author_canonical IS NOT NULL
GROUP BY author_canonical;

-- Sanity report
WITH top10 AS (
  SELECT list(author_canonical ORDER BY lifetime_commits DESC) AS top_10_names
  FROM (
    SELECT author_canonical, lifetime_commits
    FROM contributors
    WHERE author_canonical NOT LIKE 'bot:%'
    ORDER BY lifetime_commits DESC
    LIMIT 10
  )
)
SELECT 'contributors view created' AS status,
  (SELECT COUNT(*) FROM contributors) AS unique_contributors,
  (SELECT COUNT(*) FROM contributors WHERE author_canonical LIKE 'bot:%') AS bots,
  top_10_names
FROM top10;
