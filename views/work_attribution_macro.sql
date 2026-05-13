-- work_attribution_macro.sql
-- Per-commit macro work-type label via 6-signal cascade.
-- Implements the methodology in docs/analysis-playbook.md §1 + §2.
--
-- Returns one row per commit with:
--   primary_label  — one of the 10 macro categories (playbook §1)
--   confidence     — 0.0-0.95
--   signals_fired  — comma-separated list of which signals fired
--   signal_winner  — which signal set the primary_label
--
-- Cascade priority: subject_noise (0.95) > conventional_type (0.90) > branch_pattern (0.70)
--                   > embedding (0.60) > body_footer (0.55) > path_heuristic (0.40)
--
-- Depends on: setup.sql, contributors.sql
-- Parameters:
--   $org, $repo, $days_back

WITH base AS (
  SELECT
    c.sha,
    c.author_canonical AS author,
    cl_branches.branches,
    cm.subject, cm.body, cm.conventional_type, cm.top_level_dirs,
    cm.additions + cm.deletions AS churn,
    cm.changed_files,
    cm.activity_class AS old_label,
    cm.task_id, cm.pr_number, cm.authored_at, cm.is_merge_commit
  FROM contributors_resolved c
  JOIN commits_latest cm USING (sha)
  LEFT JOIN (
    SELECT sha, list(DISTINCT branch) AS branches
    FROM commit_links WHERE branch IS NOT NULL
    GROUP BY sha
  ) cl_branches USING (sha)
  WHERE c.org = $org AND ($repo = '*' OR c.repo = $repo)
    AND cm.authored_at >= now() - INTERVAL ($days_back || ' day')
),
embedding_label AS (
  -- Signal 4: highest-scoring embedding work-type label per sha
  SELECT
    unit_id AS sha,
    arg_max(category, score) AS top_emb_category,
    max(score) AS top_emb_score
  FROM semantic_categories_latest
  WHERE org = $org AND ($repo = '*' OR repo = $repo)
    AND unit_kind = 'commit' AND source = 'embedding'
    AND category IN ('feature','bug_fix','refactor','refactoring','test','test_coverage',
                     'agent_tooling','infra','chore','dependency','performance','docs')
    AND score > 0.5
  GROUP BY unit_id
),
signaled AS (
  SELECT b.*,
    e.top_emb_category, e.top_emb_score,

    -- Signal 1: subject noise
    CASE
      WHEN regexp_matches(b.subject, '^(Merge branch|Merge pull request|Merge remote-tracking)', 'i')
        THEN 'integration'
      WHEN regexp_matches(b.subject, '^Revert ', 'i')
        THEN 'integration'
      WHEN regexp_matches(b.subject, '^version updated in values-.*\.yaml', 'i')
           OR regexp_matches(b.subject, '^chore\(release\):', 'i')
        THEN 'infra_deploy'
    END AS sig1_subject_noise,

    -- Signal 2: conventional commits
    CASE lower(b.conventional_type)
      WHEN 'feat'     THEN 'feature_development'
      WHEN 'fix'      THEN 'bug_fix'
      WHEN 'refactor' THEN 'refactoring'
      WHEN 'perf'     THEN 'refactoring'
      WHEN 'test'     THEN 'testing'
      WHEN 'docs'     THEN 'docs'
      WHEN 'chore'    THEN 'maintenance'
      WHEN 'ci'       THEN 'infra_deploy'
      WHEN 'build'    THEN 'infra_deploy'
      WHEN 'revert'   THEN 'integration'
    END AS sig2_conventional,

    -- Signal 3: branch pattern (first matching branch wins)
    (
      SELECT
        CASE
          WHEN lower(branch) LIKE 'claude/%'
               OR lower(branch) LIKE 'codex/%'
               OR lower(branch) LIKE 'cursor/%'   THEN 'agent_tooling'
          WHEN lower(branch) LIKE 'feat/%'
               OR lower(branch) LIKE 'feature/%'  THEN 'feature_development'
          WHEN lower(branch) LIKE 'fix/%'
               OR lower(branch) LIKE 'hotfix/%'
               OR lower(branch) LIKE 'bugfix/%'   THEN 'bug_fix'
          WHEN lower(branch) LIKE 'refactor/%'
               OR lower(branch) = 'refactpr'
               OR lower(branch) LIKE '%refactor%' THEN 'refactoring'
          WHEN lower(branch) LIKE 'test/%'
               OR lower(branch) LIKE 'tests/%'    THEN 'testing'
          WHEN lower(branch) LIKE 'chore/%'
               OR lower(branch) LIKE 'deps/%'     THEN 'maintenance'
          WHEN lower(branch) LIKE 'docs/%'
               OR lower(branch) LIKE 'doc/%'      THEN 'docs'
          WHEN lower(branch) IN ('qa','qa-testing-branch','python-deployment','preprod','prod')
               OR lower(branch) LIKE '%deploy%'   THEN 'infra_deploy'
          WHEN regexp_matches(lower(branch), '^[a-z]+-[0-9]+') THEN 'feature_development'
        END
      FROM unnest(b.branches) AS t(branch)
      WHERE branch IS NOT NULL
      LIMIT 1
    ) AS sig3_branch,

    -- Signal 4: embedding label (mapped to macro)
    CASE e.top_emb_category
      WHEN 'feature'        THEN 'feature_development'
      WHEN 'bug_fix'        THEN 'bug_fix'
      WHEN 'refactor'       THEN 'refactoring'
      WHEN 'refactoring'    THEN 'refactoring'
      WHEN 'test'           THEN 'testing'
      WHEN 'test_coverage'  THEN 'testing'
      WHEN 'agent_tooling'  THEN 'agent_tooling'
      WHEN 'infra'          THEN 'infra_deploy'
      WHEN 'chore'          THEN 'maintenance'
      WHEN 'dependency'     THEN 'maintenance'
      WHEN 'performance'    THEN 'refactoring'
      WHEN 'docs'           THEN 'docs'
    END AS sig4_embedding,

    -- Signal 5: body footer
    CASE
      WHEN lower(b.body) LIKE '%co-authored-by: claude%'
           OR lower(b.body) LIKE '%generated by claude%'
           OR lower(b.body) LIKE '%🤖 generated%'
           OR lower(b.body) LIKE '%noreply@anthropic%' THEN 'agent_tooling'
    END AS sig5_body_footer,

    -- Signal 6: path heuristic (weakest fallback)
    CASE
      WHEN b.top_level_dirs IS NULL THEN NULL
      WHEN b.top_level_dirs IN ('.github', 'infra', 'charts', 'k8s') THEN 'infra_deploy'
      WHEN b.top_level_dirs IN ('.claude', '.opencode', '.agents') THEN 'agent_tooling'
      WHEN b.top_level_dirs = 'docs' THEN 'docs'
      WHEN b.top_level_dirs IN ('tests', 'test', '__tests__') THEN 'testing'
      WHEN b.top_level_dirs IN ('package.json', 'pnpm-lock.yaml', 'yarn.lock', 'uv.lock') THEN 'maintenance'
      ELSE 'feature_development'
    END AS sig6_path

  FROM base b
  LEFT JOIN embedding_label e ON b.sha = e.sha
)
SELECT
  sha, author, authored_at, churn, changed_files, task_id, pr_number, old_label,
  -- Cascade resolution: highest-confidence non-null signal wins
  COALESCE(
    sig1_subject_noise,
    sig2_conventional,
    sig3_branch,
    sig4_embedding,
    sig5_body_footer,
    sig6_path,
    'unclassified'
  ) AS primary_label,
  CASE
    WHEN sig1_subject_noise IS NOT NULL THEN 0.95
    WHEN sig2_conventional  IS NOT NULL THEN 0.90
    WHEN sig3_branch        IS NOT NULL THEN 0.70
    WHEN sig4_embedding     IS NOT NULL THEN LEAST(0.4 + 0.4 * top_emb_score, 0.65)
    WHEN sig5_body_footer   IS NOT NULL THEN 0.55
    WHEN sig6_path          IS NOT NULL THEN 0.40
    ELSE 0.0
  END AS confidence,
  CASE
    WHEN sig1_subject_noise IS NOT NULL THEN 'subject_noise'
    WHEN sig2_conventional  IS NOT NULL THEN 'conventional_type'
    WHEN sig3_branch        IS NOT NULL THEN 'branch_pattern'
    WHEN sig4_embedding     IS NOT NULL THEN 'embedding'
    WHEN sig5_body_footer   IS NOT NULL THEN 'body_footer'
    WHEN sig6_path          IS NOT NULL THEN 'path_heuristic'
    ELSE 'none'
  END AS signal_winner,
  array_to_string(list_filter(
    [sig1_subject_noise, sig2_conventional, sig3_branch, sig4_embedding, sig5_body_footer, sig6_path],
    x -> x IS NOT NULL
  ), ',') AS labels_proposed,
  subject
FROM signaled
ORDER BY authored_at DESC;
