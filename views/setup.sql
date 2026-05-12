-- setup.sql
-- Bootstraps de-duplicated *_latest views over raw parquet.
-- Run ONCE per DuckDB session before any analysis view.
-- No parameters. Idempotent.

-- ---------- prs_latest ----------
CREATE OR REPLACE VIEW prs_raw AS
SELECT * FROM read_parquet('output/data/**/*.parquet', union_by_name=true);

CREATE OR REPLACE VIEW prs_latest AS
SELECT * EXCLUDE (rn) FROM (
  SELECT *,
    ROW_NUMBER() OVER (PARTITION BY org, repo, pr_number ORDER BY collected_at DESC) AS rn
  FROM prs_raw
) WHERE rn = 1;

-- ---------- commits_latest ----------
CREATE OR REPLACE VIEW commits_raw AS
SELECT * FROM read_parquet('output/ledger/commits/**/*.parquet', union_by_name=true);

CREATE OR REPLACE VIEW commits_latest AS
SELECT * EXCLUDE (rn) FROM (
  SELECT *,
    ROW_NUMBER() OVER (PARTITION BY sha ORDER BY collected_at DESC) AS rn
  FROM commits_raw
) WHERE rn = 1;

-- ---------- commit_files (no dedup needed — sha+path is the natural key) ----------
CREATE OR REPLACE VIEW commit_files AS
SELECT * FROM read_parquet('output/ledger/commit_files/**/*.parquet', union_by_name=true);

-- ---------- commit_links (multiple rows per sha by design) ----------
CREATE OR REPLACE VIEW commit_links AS
SELECT * FROM read_parquet('output/ledger/commit_links/**/*.parquet', union_by_name=true);

-- ---------- branches_latest (snapshot dedup is critical here) ----------
CREATE OR REPLACE VIEW branches_raw AS
SELECT * FROM read_parquet('output/ledger/branches/**/*.parquet', union_by_name=true);

CREATE OR REPLACE VIEW branches_latest AS
SELECT * EXCLUDE (rn) FROM (
  SELECT *,
    ROW_NUMBER() OVER (PARTITION BY org, repo, branch ORDER BY collected_at DESC) AS rn
  FROM branches_raw
) WHERE rn = 1;

-- ---------- delivery_events_latest ----------
CREATE OR REPLACE VIEW delivery_events_raw AS
SELECT * FROM read_parquet('output/ledger/delivery_events/**/*.parquet', union_by_name=true);

CREATE OR REPLACE VIEW delivery_events_latest AS
SELECT * EXCLUDE (rn) FROM (
  SELECT *,
    ROW_NUMBER() OVER (PARTITION BY org, repo, delivery_sha ORDER BY collected_at DESC) AS rn
  FROM delivery_events_raw
) WHERE rn = 1;

-- ---------- semantic_categories_latest (multi-fact per unit by design) ----------
CREATE OR REPLACE VIEW semantic_categories_latest AS
SELECT * EXCLUDE (rn) FROM (
  SELECT *,
    ROW_NUMBER() OVER (
      PARTITION BY org, repo, unit_kind, unit_id, category, source
      ORDER BY classified_at DESC
    ) AS rn
  FROM read_parquet('output/ledger/semantic_categories/**/*.parquet', union_by_name=true)
) WHERE rn = 1;

-- ---------- semantic_embeddings_latest ----------
CREATE OR REPLACE VIEW semantic_embeddings_latest AS
SELECT * EXCLUDE (rn) FROM (
  SELECT *,
    ROW_NUMBER() OVER (
      PARTITION BY org, repo, unit_kind, unit_id, embedding_model
      ORDER BY embedded_at DESC NULLS LAST
    ) AS rn
  FROM read_parquet('output/ledger/semantic_embeddings/**/*.parquet', union_by_name=true)
) WHERE rn = 1;

-- Sanity check
SELECT 'setup complete' AS status,
  (SELECT COUNT(*) FROM commits_latest) AS commits,
  (SELECT COUNT(*) FROM prs_latest) AS prs,
  (SELECT COUNT(*) FROM branches_latest) AS branches,
  (SELECT COUNT(*) FROM semantic_categories_latest) AS semantic_facts,
  (SELECT COUNT(*) FROM semantic_embeddings_latest) AS embeddings;
