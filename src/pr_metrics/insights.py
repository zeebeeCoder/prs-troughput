"""Reusable DuckDB insight slices over the PR metrics delivery lake."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd
from tabulate import tabulate


@dataclass(frozen=True)
class Insight:
    """A named SQL slice over canonical delivery-lake views."""

    description: str
    required_views: tuple[str, ...]
    sql: str


INSIGHTS: dict[str, Insight] = {
    "active_repos": Insight(
        description="Rank repositories by recent PR intensity for evaluation-contract selection.",
        required_views=("prs_latest",),
        sql="""
            SELECT
                org,
                repo,
                COUNT(*) AS prs,
                COUNT(*) FILTER (WHERE state = 'merged') AS merged_prs,
                COUNT(*) FILTER (WHERE state = 'open') AS open_prs,
                COUNT(DISTINCT author) AS authors,
                SUM(COALESCE(pr_size, 0)) AS pr_churn,
                MAX(created_at)::DATE AS latest_pr
            FROM prs_latest
            GROUP BY org, repo
            ORDER BY prs DESC, latest_pr DESC
            LIMIT 25
        """,
    ),
    "intensity_weekly": Insight(
        description="Weekly activity heatmap grain by repo, actor, and delivery lane.",
        required_views=("prs_latest", "commits_latest"),
        sql="""
            WITH events AS (
                SELECT
                    date_trunc('week', created_at) AS bucket,
                    org,
                    repo,
                    author AS actor,
                    'pr_created' AS lane,
                    COUNT(*) AS events,
                    SUM(COALESCE(pr_size, 0)) AS intensity_units
                FROM prs_latest
                WHERE created_at IS NOT NULL
                GROUP BY 1, 2, 3, 4, 5

                UNION ALL

                SELECT
                    date_trunc('week', merged_at) AS bucket,
                    org,
                    repo,
                    COALESCE(merged_by, author) AS actor,
                    'pr_merged' AS lane,
                    COUNT(*) AS events,
                    SUM(COALESCE(pr_size, 0)) AS intensity_units
                FROM prs_latest
                WHERE merged_at IS NOT NULL
                GROUP BY 1, 2, 3, 4, 5

                UNION ALL

                SELECT
                    date_trunc('week', committed_at) AS bucket,
                    org,
                    repo,
                    COALESCE(author_name, author_email, 'unknown') AS actor,
                    CASE WHEN is_direct_main THEN 'direct_main_commit' ELSE 'default_branch_commit' END AS lane,
                    COUNT(*) AS events,
                    SUM(COALESCE(additions, 0) + COALESCE(deletions, 0)) AS intensity_units
                FROM commits_latest
                WHERE committed_at IS NOT NULL
                GROUP BY 1, 2, 3, 4, 5
            )
            SELECT *
            FROM events
            ORDER BY bucket DESC, org, repo, lane, events DESC
            LIMIT 200
        """,
    ),
    "kinetics_weekly": Insight(
        description="Weekly repo-level authored commit, delivery, and PR velocity signals by explicit grain.",
        required_views=("prs_latest", "commits_latest", "delivery_events_latest"),
        sql="""
            WITH weeks AS (
                SELECT date_trunc('week', created_at) AS week, org, repo FROM prs_latest WHERE created_at IS NOT NULL
                UNION
                SELECT date_trunc('week', committed_at) AS week, org, repo FROM commits_latest WHERE committed_at IS NOT NULL
                UNION
                SELECT date_trunc('week', delivered_at) AS week, org, repo FROM delivery_events_latest WHERE delivered_at IS NOT NULL
            ),
            pr_metrics AS (
                SELECT
                    date_trunc('week', created_at) AS week,
                    org,
                    repo,
                    COUNT(*) AS pr_created,
                    COUNT(*) FILTER (WHERE state = 'merged') AS pr_merged,
                    SUM(COALESCE(pr_size, 0)) AS pr_churn
                FROM prs_latest
                WHERE created_at IS NOT NULL
                GROUP BY 1, 2, 3
            ),
            commit_metrics AS (
                SELECT
                    date_trunc('week', committed_at) AS week,
                    org,
                    repo,
                    COUNT(*) AS authored_commit_events,
                    COUNT(*) FILTER (WHERE COALESCE(source_kinds, 'default_branch') LIKE '%default_branch%') AS default_branch_commit_events,
                    SUM(COALESCE(additions, 0) + COALESCE(deletions, 0)) AS commit_churn,
                    COUNT(DISTINCT author_email) AS commit_authors
                FROM commits_latest
                WHERE committed_at IS NOT NULL
                GROUP BY 1, 2, 3
            ),
            delivery_metrics AS (
                SELECT
                    date_trunc('week', delivered_at) AS week,
                    org,
                    repo,
                    COUNT(*) AS delivered_commit_events,
                    COUNT(*) FILTER (WHERE delivery_mode = 'direct_main_candidate') AS direct_main_candidates,
                    COUNT(*) FILTER (WHERE pr_number IS NOT NULL) AS pr_linked_delivery_events
                FROM delivery_events_latest
                WHERE delivered_at IS NOT NULL
                GROUP BY 1, 2, 3
            ),
            weekly AS (
                SELECT
                    w.week,
                    w.org,
                    w.repo,
                    COALESCE(p.pr_created, 0) AS pr_created,
                    COALESCE(p.pr_merged, 0) AS pr_merged,
                    COALESCE(c.authored_commit_events, 0) AS authored_commit_events,
                    COALESCE(c.default_branch_commit_events, 0) AS default_branch_commit_events,
                    COALESCE(d.delivered_commit_events, 0) AS delivered_commit_events,
                    COALESCE(d.direct_main_candidates, 0) AS direct_main_candidates,
                    COALESCE(d.pr_linked_delivery_events, 0) AS pr_linked_delivery_events,
                    COALESCE(p.pr_churn, 0) + COALESCE(c.commit_churn, 0) AS total_churn,
                    COALESCE(c.commit_authors, 0) AS commit_authors
                FROM weeks w
                LEFT JOIN pr_metrics p USING (week, org, repo)
                LEFT JOIN commit_metrics c USING (week, org, repo)
                LEFT JOIN delivery_metrics d USING (week, org, repo)
            )
            SELECT
                week::DATE AS week,
                org,
                repo,
                pr_created,
                pr_merged,
                authored_commit_events,
                default_branch_commit_events,
                delivered_commit_events,
                direct_main_candidates,
                ROUND(100.0 * direct_main_candidates / NULLIF(delivered_commit_events, 0), 1) AS direct_main_delivery_pct,
                pr_linked_delivery_events,
                total_churn,
                commit_authors,
                authored_commit_events - LAG(authored_commit_events) OVER (PARTITION BY org, repo ORDER BY week) AS authored_commit_velocity_delta,
                delivered_commit_events - LAG(delivered_commit_events) OVER (PARTITION BY org, repo ORDER BY week) AS delivery_velocity_delta,
                total_churn - LAG(total_churn) OVER (PARTITION BY org, repo ORDER BY week) AS churn_delta,
                pr_created - LAG(pr_created) OVER (PARTITION BY org, repo ORDER BY week) AS pr_velocity_delta
            FROM weekly
            ORDER BY week DESC, org, repo
            LIMIT 120
        """,
    ),
    "review_queue": Insight(
        description="Open PR queue buckets: reviewer, author, CI, mergeability, and stale idle work.",
        required_views=("prs_latest",),
        sql="""
            SELECT
                org,
                repo,
                pr_number,
                title,
                author,
                created_at::DATE AS created,
                updated_at::DATE AS updated,
                date_diff('day', created_at, current_timestamp) AS age_days,
                date_diff('day', COALESCE(updated_at, created_at), current_timestamp) AS idle_days,
                review_decision,
                review_request_count,
                requested_reviewers,
                approvals_count,
                changes_requested_count,
                ci_state,
                checks_failed_count,
                checks_pending_count,
                mergeable,
                merge_state_status,
                CASE
                    WHEN COALESCE(checks_failed_count, 0) > 0 THEN 'ci_failed'
                    WHEN COALESCE(changes_requested_count, 0) > 0 THEN 'waiting_on_author'
                    WHEN COALESCE(checks_pending_count, 0) > 0 OR ci_state = 'pending' THEN 'ci_pending'
                    WHEN COALESCE(review_request_count, 0) > 0 OR review_decision = 'REVIEW_REQUIRED' THEN 'waiting_on_review'
                    WHEN merge_state_status IS NOT NULL AND merge_state_status NOT IN ('CLEAN', 'UNKNOWN') THEN 'merge_blocked'
                    WHEN date_diff('day', COALESCE(updated_at, created_at), current_timestamp) >= 7 THEN 'stale_open'
                    ELSE 'open_unclassified'
                END AS queue_bucket,
                url
            FROM prs_latest
            WHERE state = 'open'
            ORDER BY age_days DESC, org, repo, pr_number
            LIMIT 200
        """,
    ),
    "invisible_wip": Insight(
        description="Latest branch snapshots ahead of default without an open PR, excluding semantic environment lanes.",
        required_views=("branches_latest",),
        sql="""
            WITH branch_roles AS (
                SELECT
                    org,
                    repo,
                    unit_id AS branch,
                    string_agg(category, ',') AS branch_roles
                FROM semantic_categories_latest
                WHERE unit_kind = 'branch'
                  AND category_namespace = 'branch_role'
                GROUP BY 1, 2, 3
            )
            SELECT
                b.org,
                b.repo,
                b.branch,
                COALESCE(r.branch_roles, 'uncategorized') AS branch_roles,
                b.ahead_main,
                b.behind_main,
                b.last_author,
                b.last_commit_at::DATE AS last_commit,
                date_diff('day', b.last_commit_at, current_timestamp) AS idle_days,
                b.task_id,
                b.spec_name,
                b.head_sha
            FROM branches_latest b
            LEFT JOIN branch_roles r
              ON r.org = b.org
             AND r.repo = b.repo
             AND r.branch = b.branch
            WHERE COALESCE(b.ahead_main, 0) > 0
              AND NOT COALESCE(b.has_open_pr, false)
              AND NOT EXISTS (
                  SELECT 1
                  FROM semantic_categories_latest excluded
                  WHERE excluded.org = b.org
                    AND excluded.repo = b.repo
                    AND excluded.unit_kind = 'branch'
                    AND excluded.unit_id = b.branch
                    AND excluded.category_namespace = 'branch_role'
                    AND excluded.category IN ('environment', 'deployment', 'release', 'bot_generated')
              )
            ORDER BY b.last_commit_at DESC, b.ahead_main DESC
            LIMIT 200
        """,
    ),
    "refactoring_activity": Insight(
        description="Refactor-attributed commits, PRs, and branches by explicit semantic category facts.",
        required_views=("semantic_categories_latest", "commits_latest", "prs_latest", "branches_latest"),
        sql="""
            WITH refactor_units AS (
                SELECT DISTINCT org, repo, unit_kind, unit_id
                FROM semantic_categories_latest
                WHERE (category_namespace = 'work_type' AND category = 'refactor')
                   OR (category_namespace = 'quality' AND category = 'refactoring')
            ),
            units AS (
                SELECT
                    c.org,
                    c.repo,
                    'commit' AS unit_kind,
                    c.sha AS unit_id,
                    c.committed_at AS observed_at,
                    COALESCE(c.author_name, c.author_email, 'unknown') AS actor,
                    c.task_id,
                    c.spec_name,
                    COALESCE(c.additions, 0) + COALESCE(c.deletions, 0) AS churn,
                    c.subject AS summary
                FROM commits_latest c

                UNION ALL

                SELECT
                    p.org,
                    p.repo,
                    'pr' AS unit_kind,
                    CAST(p.pr_number AS VARCHAR) AS unit_id,
                    COALESCE(p.merged_at, p.updated_at, p.created_at) AS observed_at,
                    COALESCE(p.author, 'unknown') AS actor,
                    p.task_id,
                    p.spec_name,
                    COALESCE(p.pr_size, 0) AS churn,
                    p.title AS summary
                FROM prs_latest p

                UNION ALL

                SELECT
                    b.org,
                    b.repo,
                    'branch' AS unit_kind,
                    b.branch AS unit_id,
                    b.last_commit_at AS observed_at,
                    COALESCE(b.last_author, 'unknown') AS actor,
                    b.task_id,
                    b.spec_name,
                    COALESCE(b.ahead_main, 0) AS churn,
                    b.branch AS summary
                FROM branches_latest b
            )
            SELECT
                date_trunc('week', u.observed_at)::DATE AS week,
                u.org,
                u.repo,
                u.actor,
                u.unit_kind,
                COUNT(*) AS units,
                SUM(u.churn) AS churn,
                COUNT(u.task_id) AS ticket_linked_units,
                COUNT(u.spec_name) AS spec_linked_units,
                string_agg(DISTINCT u.task_id, ',') FILTER (WHERE u.task_id IS NOT NULL) AS task_ids,
                string_agg(DISTINCT u.spec_name, ',') FILTER (WHERE u.spec_name IS NOT NULL) AS spec_names
            FROM units u
            JOIN refactor_units r
              ON r.org = u.org
             AND r.repo = u.repo
             AND r.unit_kind = u.unit_kind
             AND r.unit_id = u.unit_id
            WHERE u.observed_at IS NOT NULL
            GROUP BY 1, 2, 3, 4, 5
            ORDER BY week DESC, churn DESC, units DESC
            LIMIT 200
        """,
    ),
    "direct_main_risk": Insight(
        description="Direct default-branch commits with churn, file, test, generated, and sensitive-path flags.",
        required_views=("commits_latest", "commit_files_latest"),
        sql="""
            WITH file_flags AS (
                SELECT
                    org,
                    repo,
                    sha,
                    COUNT(*) AS file_rows,
                    SUM(COALESCE(additions, 0) + COALESCE(deletions, 0)) AS file_churn,
                    SUM(CASE WHEN is_test THEN 1 ELSE 0 END) AS test_files,
                    SUM(CASE WHEN is_generated THEN 1 ELSE 0 END) AS generated_files,
                    SUM(CASE WHEN is_sensitive THEN 1 ELSE 0 END) AS sensitive_files
                FROM commit_files_latest
                GROUP BY 1, 2, 3
            )
            SELECT
                c.org,
                c.repo,
                c.committed_at::DATE AS committed,
                substr(c.sha, 1, 8) AS sha,
                c.author_name,
                c.activity_class,
                c.conventional_type,
                COALESCE(c.additions, 0) + COALESCE(c.deletions, 0) AS churn,
                c.changed_files,
                COALESCE(f.test_files, 0) AS test_files,
                COALESCE(f.sensitive_files, 0) AS sensitive_files,
                COALESCE(f.generated_files, 0) AS generated_files,
                (
                    CASE WHEN COALESCE(c.additions, 0) + COALESCE(c.deletions, 0) >= 1000 THEN 2 ELSE 0 END +
                    CASE WHEN COALESCE(c.changed_files, 0) >= 20 THEN 1 ELSE 0 END +
                    CASE WHEN COALESCE(f.sensitive_files, 0) > 0 THEN 2 ELSE 0 END +
                    CASE WHEN COALESCE(f.test_files, 0) = 0 AND c.activity_class IN ('feature_dev', 'bug_fix', 'security_auth') THEN 1 ELSE 0 END
                ) AS risk_score,
                c.task_id,
                c.spec_name,
                c.subject
            FROM commits_latest c
            LEFT JOIN file_flags f USING (org, repo, sha)
            WHERE c.is_direct_main
            ORDER BY risk_score DESC, churn DESC, c.committed_at DESC
            LIMIT 200
        """,
    ),
    "traceability": Insight(
        description="Coverage of task/spec markers across PR, commit, and branch grains.",
        required_views=("prs_latest", "commits_latest", "branches_latest"),
        sql="""
            SELECT
                'prs' AS dataset,
                COUNT(*) AS total_rows,
                COUNT(task_id) AS with_task_id,
                ROUND(100.0 * COUNT(task_id) / NULLIF(COUNT(*), 0), 1) AS task_id_pct,
                COUNT(spec_name) AS with_spec_name,
                ROUND(100.0 * COUNT(spec_name) / NULLIF(COUNT(*), 0), 1) AS spec_name_pct
            FROM prs_latest

            UNION ALL

            SELECT
                'commits' AS dataset,
                COUNT(*) AS total_rows,
                COUNT(task_id) AS with_task_id,
                ROUND(100.0 * COUNT(task_id) / NULLIF(COUNT(*), 0), 1) AS task_id_pct,
                COUNT(spec_name) AS with_spec_name,
                ROUND(100.0 * COUNT(spec_name) / NULLIF(COUNT(*), 0), 1) AS spec_name_pct
            FROM commits_latest

            UNION ALL

            SELECT
                'branches' AS dataset,
                COUNT(*) AS total_rows,
                COUNT(task_id) AS with_task_id,
                ROUND(100.0 * COUNT(task_id) / NULLIF(COUNT(*), 0), 1) AS task_id_pct,
                COUNT(spec_name) AS with_spec_name,
                ROUND(100.0 * COUNT(spec_name) / NULLIF(COUNT(*), 0), 1) AS spec_name_pct
            FROM branches_latest
        """,
    ),
    "untraced_units": Insight(
        description="Actionable unit-level PR, commit, and branch rows missing task/spec traceability.",
        required_views=("prs_latest", "commits_latest", "branches_latest"),
        sql="""
            WITH category_rollup AS (
                SELECT
                    org,
                    repo,
                    unit_kind,
                    unit_id,
                    string_agg(category, ',') FILTER (WHERE category_namespace = 'work_type') AS work_types,
                    string_agg(category, ',') FILTER (WHERE category_namespace = 'branch_role') AS branch_roles,
                    string_agg(category, ',') FILTER (WHERE category_namespace = 'component') AS components
                FROM semantic_categories_latest
                GROUP BY 1, 2, 3, 4
            ),
            units AS (
                SELECT
                    p.org,
                    p.repo,
                    'pr' AS unit_kind,
                    CAST(p.pr_number AS VARCHAR) AS unit_id,
                    COALESCE(p.updated_at, p.created_at) AS observed_at,
                    COALESCE(p.author, 'unknown') AS actor,
                    p.title AS summary,
                    COALESCE(p.pr_size, 0) AS churn,
                    COALESCE(p.changed_files, 0) AS changed_files,
                    p.url,
                    p.head_sha,
                    p.task_id,
                    p.spec_name
                FROM prs_latest p

                UNION ALL

                SELECT
                    c.org,
                    c.repo,
                    'commit' AS unit_kind,
                    c.sha AS unit_id,
                    c.committed_at AS observed_at,
                    COALESCE(c.author_name, c.author_email, 'unknown') AS actor,
                    c.subject AS summary,
                    COALESCE(c.additions, 0) + COALESCE(c.deletions, 0) AS churn,
                    COALESCE(c.changed_files, 0) AS changed_files,
                    NULL AS url,
                    c.sha AS head_sha,
                    c.task_id,
                    c.spec_name
                FROM commits_latest c

                UNION ALL

                SELECT
                    b.org,
                    b.repo,
                    'branch' AS unit_kind,
                    b.branch AS unit_id,
                    b.last_commit_at AS observed_at,
                    COALESCE(b.last_author, 'unknown') AS actor,
                    b.branch AS summary,
                    COALESCE(b.ahead_main, 0) AS churn,
                    0 AS changed_files,
                    b.pr_url AS url,
                    b.head_sha,
                    b.task_id,
                    b.spec_name
                FROM branches_latest b
            )
            SELECT
                u.unit_kind,
                u.unit_id,
                u.org,
                u.repo,
                u.actor,
                u.observed_at::DATE AS observed,
                COALESCE(r.work_types, 'uncategorized') AS work_types,
                COALESCE(r.branch_roles, 'none') AS branch_roles,
                COALESCE(r.components, 'none') AS components,
                u.churn,
                u.changed_files,
                u.summary,
                u.url,
                u.head_sha
            FROM units u
            LEFT JOIN category_rollup r
              ON r.org = u.org
             AND r.repo = u.repo
             AND r.unit_kind = u.unit_kind
             AND r.unit_id = u.unit_id
            WHERE u.task_id IS NULL
              AND u.spec_name IS NULL
            ORDER BY u.churn DESC, u.changed_files DESC, u.observed_at DESC NULLS LAST
            LIMIT 300
        """,
    ),
    "traceability_breakdown": Insight(
        description="Traceability coverage by week, actor, unit kind, repo, and semantic work type.",
        required_views=("prs_latest", "commits_latest", "branches_latest"),
        sql="""
            WITH category_rollup AS (
                SELECT
                    org,
                    repo,
                    unit_kind,
                    unit_id,
                    string_agg(category, ',') FILTER (WHERE category_namespace = 'work_type') AS work_types,
                    string_agg(category, ',') FILTER (WHERE category_namespace = 'branch_role') AS branch_roles
                FROM semantic_categories_latest
                GROUP BY 1, 2, 3, 4
            ),
            units AS (
                SELECT
                    p.org,
                    p.repo,
                    'pr' AS unit_kind,
                    CAST(p.pr_number AS VARCHAR) AS unit_id,
                    COALESCE(p.updated_at, p.created_at) AS observed_at,
                    COALESCE(p.author, 'unknown') AS actor,
                    COALESCE(p.pr_size, 0) AS churn,
                    p.task_id,
                    p.spec_name
                FROM prs_latest p

                UNION ALL

                SELECT
                    c.org,
                    c.repo,
                    'commit' AS unit_kind,
                    c.sha AS unit_id,
                    c.committed_at AS observed_at,
                    COALESCE(c.author_name, c.author_email, 'unknown') AS actor,
                    COALESCE(c.additions, 0) + COALESCE(c.deletions, 0) AS churn,
                    c.task_id,
                    c.spec_name
                FROM commits_latest c

                UNION ALL

                SELECT
                    b.org,
                    b.repo,
                    'branch' AS unit_kind,
                    b.branch AS unit_id,
                    b.last_commit_at AS observed_at,
                    COALESCE(b.last_author, 'unknown') AS actor,
                    COALESCE(b.ahead_main, 0) AS churn,
                    b.task_id,
                    b.spec_name
                FROM branches_latest b
            ),
            enriched AS (
                SELECT
                    u.*,
                    COALESCE(r.work_types, r.branch_roles, 'uncategorized') AS semantic_group,
                    (u.task_id IS NOT NULL OR u.spec_name IS NOT NULL) AS is_traced
                FROM units u
                LEFT JOIN category_rollup r
                  ON r.org = u.org
                 AND r.repo = u.repo
                 AND r.unit_kind = u.unit_kind
                 AND r.unit_id = u.unit_id
            )
            SELECT
                date_trunc('week', observed_at)::DATE AS week,
                org,
                repo,
                unit_kind,
                actor,
                semantic_group,
                COUNT(*) AS units,
                COUNT(*) FILTER (WHERE is_traced) AS traced_units,
                COUNT(*) FILTER (WHERE NOT is_traced) AS untraced_units,
                ROUND(100.0 * COUNT(*) FILTER (WHERE is_traced) / NULLIF(COUNT(*), 0), 1) AS traced_pct,
                SUM(churn) AS churn,
                SUM(churn) FILTER (WHERE NOT is_traced) AS untraced_churn
            FROM enriched
            WHERE observed_at IS NOT NULL
            GROUP BY 1, 2, 3, 4, 5, 6
            ORDER BY week DESC, untraced_churn DESC NULLS LAST, untraced_units DESC, units DESC
            LIMIT 300
        """,
    ),
    "activity_mix": Insight(
        description="Semantic work mix by repo and activity class.",
        required_views=("commits_latest",),
        sql="""
            SELECT
                org,
                repo,
                activity_class,
                COUNT(*) AS commits,
                COUNT(*) FILTER (WHERE is_direct_main) AS direct_main_commits,
                SUM(COALESCE(additions, 0) + COALESCE(deletions, 0)) AS churn,
                SUM(COALESCE(changed_files, 0)) AS changed_files
            FROM commits_latest
            GROUP BY org, repo, activity_class
            ORDER BY org, repo, commits DESC, churn DESC
            LIMIT 200
        """,
    ),
}


def _has_parquet(dataset_dir: Path) -> bool:
    return dataset_dir.exists() and any(dataset_dir.glob("**/*.parquet"))


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _repo_filter(repo: str | None) -> str | None:
    if not repo:
        return None
    repos = [item.strip() for item in repo.split(",") if item.strip()]
    if len(repos) == 1:
        return f"repo = {_quote(repos[0])}"
    return f"repo IN ({', '.join(_quote(item) for item in repos)})"


def _where_clause(org: str | None, repo: str | None, days_back: int | None, date_column: str | None) -> str:
    clauses = []
    if org:
        clauses.append(f"org = {_quote(org)}")
    repo_clause = _repo_filter(repo)
    if repo_clause:
        clauses.append(repo_clause)
    if days_back and date_column:
        clauses.append(f"{date_column} >= current_timestamp - INTERVAL {int(days_back)} DAY")
    return f" WHERE {' AND '.join(clauses)}" if clauses else ""


def _create_raw_view(
    con: duckdb.DuckDBPyConnection,
    view_name: str,
    dataset_dir: Path,
    org: str | None,
    repo: str | None,
    days_back: int | None,
    date_column: str | None,
) -> bool:
    if not _has_parquet(dataset_dir):
        return False

    where_clause = _where_clause(org, repo, days_back, date_column)
    con.execute(f"""
        CREATE OR REPLACE VIEW {view_name} AS
        SELECT *
        FROM read_parquet('{dataset_dir}/**/*.parquet', hive_partitioning=true, union_by_name=true)
        {where_clause}
    """)
    return True



def _create_latest_view(con, source_view: str, latest_view: str, partition_by: str, order_by: str) -> None:
    """Create a latest-row view over a raw delivery-lake dataset."""
    con.execute(f"""
        CREATE OR REPLACE VIEW {latest_view} AS
        SELECT * EXCLUDE (rn)
        FROM (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY {partition_by}
                    ORDER BY {order_by} DESC NULLS LAST
                ) AS rn
            FROM {source_view}
        )
        WHERE rn = 1
    """)


DELIVERY_DATASETS = (
    {
        "raw_view": "prs_raw",
        "latest_view": "prs_latest",
        "relative_dir": ("data",),
        "days_back": "configured",
        "date_column": "created_at",
        "partition_by": "org, repo, pr_number",
        "order_by": "COALESCE(collected_at, updated_at, created_at)",
    },
    {
        "raw_view": "commits_raw",
        "latest_view": "commits_latest",
        "relative_dir": ("ledger", "commits"),
        "days_back": "configured",
        "date_column": "committed_at",
        "partition_by": "org, repo, sha",
        "order_by": "COALESCE(collected_at, committed_at)",
    },
    {
        "raw_view": "branches_raw",
        "latest_view": "branches_latest",
        "relative_dir": ("ledger", "branches"),
        "days_back": None,
        "date_column": None,
        "partition_by": "org, repo, branch",
        "order_by": "COALESCE(collected_at, last_commit_at)",
    },
    {
        "raw_view": "commit_links_raw",
        "latest_view": "commit_links_latest",
        "relative_dir": ("ledger", "commit_links"),
        "days_back": "configured",
        "date_column": "observed_at",
        "partition_by": "org, repo, sha, source_kind, source_id",
        "order_by": "COALESCE(collected_at, observed_at)",
    },
    {
        "raw_view": "delivery_events_raw",
        "latest_view": "delivery_events_latest",
        "relative_dir": ("ledger", "delivery_events"),
        "days_back": "configured",
        "date_column": "delivered_at",
        "partition_by": "org, repo, delivery_sha",
        "order_by": "COALESCE(collected_at, delivered_at)",
    },
    {
        "raw_view": "commit_files_raw",
        "latest_view": "commit_files_latest",
        "relative_dir": ("ledger", "commit_files"),
        "days_back": "configured",
        "date_column": None,
        "partition_by": "org, repo, sha, path",
        "order_by": "collected_at",
    },
    {
        "raw_view": "semantic_categories_raw",
        "latest_view": "semantic_categories_latest",
        "relative_dir": ("ledger", "semantic_categories"),
        "days_back": "configured",
        "date_column": "observed_at",
        "partition_by": "org, repo, unit_kind, unit_id, category_namespace, category",
        "order_by": "COALESCE(classified_at, observed_at)",
    },
)


def _dataset_path(root: Path, config: dict) -> Path:
    """Return the parquet directory path for a delivery dataset config."""
    path = root
    for part in config["relative_dir"]:
        path /= part
    return path


def _dataset_days_back(config: dict, days_back: int | None) -> int | None:
    """Resolve per-dataset days-back policy."""
    return days_back if config["days_back"] == "configured" else config["days_back"]


def _create_delivery_dataset_views(con, root: Path, config: dict, org, repo, days_back) -> set[str]:
    """Create raw/latest views for one delivery-lake dataset when parquet exists."""
    if not _create_raw_view(
        con,
        config["raw_view"],
        _dataset_path(root, config),
        org,
        repo,
        _dataset_days_back(config, days_back),
        config["date_column"],
    ):
        return set()

    _create_latest_view(
        con,
        config["raw_view"],
        config["latest_view"],
        config["partition_by"],
        config["order_by"],
    )
    return {config["raw_view"], config["latest_view"]}


def _view_columns(con, view_name: str) -> set[str]:
    """Return column names for an existing DuckDB view."""
    return set(con.execute(f"DESCRIBE {view_name}").fetchdf()["column_name"])


def _ensure_view_columns(con, view_name: str, defaults: dict[str, str]) -> None:
    """Add compatibility columns to a latest view when older parquet lacks them."""
    columns = _view_columns(con, view_name)
    missing = {name: expr for name, expr in defaults.items() if name not in columns}
    if not missing:
        return
    temp_name = f"_{view_name}_compat"
    default_select = ", ".join(f"{expr} AS {name}" for name, expr in missing.items())
    con.execute(f"CREATE OR REPLACE TEMP TABLE {temp_name} AS SELECT *, {default_select} FROM {view_name}")
    con.execute(f"CREATE OR REPLACE VIEW {view_name} AS SELECT * FROM {temp_name}")


def _delivery_mode_sql() -> str:
    """Return SQL that classifies legacy default-branch commits as delivery events."""
    return """
        CASE
            WHEN pr_number IS NOT NULL AND COALESCE(parent_count, 0) > 1 THEN 'merge_commit'
            WHEN pr_number IS NOT NULL THEN 'squash'
            WHEN COALESCE(parent_count, 0) > 1 THEN 'merge_commit'
            ELSE 'direct_main_candidate'
        END
    """


def _create_legacy_delivery_events_view(con, available: set[str]) -> None:
    """Synthesize delivery events from older commit-only ledgers when needed."""
    if "delivery_events_latest" in available or "commits_latest" not in available:
        return
    _ensure_view_columns(con, "commits_latest", {
        "source_kinds": "'default_branch'",
        "on_main": "true",
        "pr_number": "NULL::INTEGER",
        "parent_count": "NULL::INTEGER",
    })
    con.execute(f"""
        CREATE OR REPLACE VIEW delivery_events_latest AS
        SELECT
            org,
            repo,
            year,
            month,
            collected_at,
            sha AS delivery_sha,
            committed_at AS delivered_at,
            {_delivery_mode_sql()} AS delivery_mode,
            pr_number,
            'legacy_commits_latest' AS evidence
        FROM commits_latest
        WHERE COALESCE(on_main, true)
    """)
    available.add("delivery_events_latest")


def _create_empty_semantic_categories_view(con, available: set[str]) -> None:
    """Create an empty semantic view so branch insights can use optional categories."""
    if "semantic_categories_latest" in available:
        return
    con.execute("""
        CREATE OR REPLACE VIEW semantic_categories_latest AS
        SELECT *
        FROM (
            SELECT
                ''::VARCHAR AS org,
                ''::VARCHAR AS repo,
                NULL::INTEGER AS year,
                NULL::INTEGER AS month,
                ''::VARCHAR AS unit_kind,
                ''::VARCHAR AS unit_id,
                ''::VARCHAR AS category_namespace,
                ''::VARCHAR AS category,
                NULL::DOUBLE AS score,
                ''::VARCHAR AS confidence,
                ''::VARCHAR AS source,
                ''::VARCHAR AS evidence,
                ''::VARCHAR AS classifier_version,
                ''::VARCHAR AS taxonomy_version,
                ''::VARCHAR AS embedding_model,
                NULL::TIMESTAMP AS classified_at,
                NULL::TIMESTAMP AS observed_at
        )
        WHERE false
    """)


def _apply_compatibility_views(con, available: set[str]) -> None:
    """Create compatibility views for old parquet schemas where safe."""
    if "commits_latest" in available:
        _ensure_view_columns(con, "commits_latest", {
            "source_kinds": "'default_branch'",
            "on_main": "true",
            "pr_number": "NULL::INTEGER",
            "parent_count": "NULL::INTEGER",
        })
    _create_legacy_delivery_events_view(con, available)
    _create_empty_semantic_categories_view(con, available)


def create_delivery_lake_views(
    output_dir: str = "output",
    org: str | None = None,
    repo: str | None = None,
    days_back: int | None = None,
) -> tuple[duckdb.DuckDBPyConnection, set[str]]:
    """Create canonical latest/snapshot DuckDB views over available parquet datasets."""
    con = duckdb.connect()
    root = Path(output_dir)
    available: set[str] = set()
    for config in DELIVERY_DATASETS:
        available.update(_create_delivery_dataset_views(con, root, config, org, repo, days_back))
    _apply_compatibility_views(con, available)
    return con, available


def run_insight(
    name: str,
    output_dir: str = "output",
    org: str | None = None,
    repo: str | None = None,
    days_back: int | None = None,
) -> pd.DataFrame:
    """Run a named insight query and return a dataframe."""
    if name not in INSIGHTS:
        raise ValueError(f"Unknown insight '{name}'. Available: {', '.join(sorted(INSIGHTS))}")

    con, available = create_delivery_lake_views(output_dir=output_dir, org=org, repo=repo, days_back=days_back)
    try:
        insight = INSIGHTS[name]
        missing = sorted(set(insight.required_views) - available)
        if missing:
            raise ValueError(
                f"Insight '{name}' requires missing dataset views: {', '.join(missing)}. "
                "Refresh the needed PR/commit/branch data first."
            )
        return con.execute(insight.sql).fetchdf()
    finally:
        con.close()


def render_dataframe(df: pd.DataFrame, output_format: str = "table") -> str:
    """Render an insight dataframe as table, JSON, or CSV text."""
    if output_format == "json":
        return df.to_json(orient="records", date_format="iso", indent=2)
    if output_format == "csv":
        return df.to_csv(index=False)
    if df.empty:
        return "No rows"
    return tabulate(df, headers="keys", tablefmt="github", showindex=False)
