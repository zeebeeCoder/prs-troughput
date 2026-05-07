"""Deterministic semantic category facts for delivery ledger units."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
import re
from typing import Any, Iterable

import pandas as pd

from .parsers import is_generated_path, is_sensitive_path, is_test_path, parse_conventional_commit

TAXONOMY_VERSION = "semantic-taxonomy-v1"
CLASSIFIER_VERSION = "deterministic-rules-v1"
EMBEDDING_CLASSIFIER_VERSION = "embedding-sim-v1"
EMBEDDING_MODEL = "none"
DEFAULT_EMBEDDING_THRESHOLD = 0.72

TICKET_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")

WORK_TYPE_FROM_CONVENTIONAL = {
    "feat": "feature",
    "fix": "bug_fix",
    "refactor": "refactor",
    "docs": "docs",
    "test": "test",
    "chore": "chore",
    "ci": "infra",
    "build": "dependency",
    "perf": "performance",
    "revert": "chore",
}

WORK_TYPE_FROM_ACTIVITY = {
    "feature_dev": "feature",
    "bug_fix": "bug_fix",
    "refactor": "refactor",
    "docs": "docs",
    "test": "test",
    "maintenance": "chore",
    "ci": "infra",
    "build_dependency": "dependency",
    "performance": "performance",
    "agent_tooling": "agent_tooling",
    "infra": "infra",
    "dependency": "dependency",
    "security_auth": "security_auth",
}

ENVIRONMENT_BRANCHES = {"qa", "uat", "dev", "develop", "development", "staging", "stage", "production", "prod", "main", "master"}
COMPONENT_KEYWORDS = {
    "backend": ("backend", "api", "server", "service"),
    "frontend": ("frontend", "web", "ui", "client", "app"),
    "data": ("data", "analytics", "duckdb", "parquet", "ledger", "warehouse"),
    "infra": ("infra", "deploy", "deployment", "terraform", "pulumi", "ci", "docker", "k8s", "kamal"),
    "auth": ("auth", "oauth", "jwt", "token", "permission", "rbac"),
    "oracle": ("oracle",),
    "payments": ("payment", "billing", "stripe", "invoice"),
    "onboarding": ("onboarding", "signup", "activation"),
}


@dataclass(frozen=True)
class SemanticUnit:
    """Common semantic envelope for a delivery-lake unit."""

    kind: str
    unit_id: str
    org: str
    repo: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CategoryFact:
    """One semantic category assignment for one unit."""

    category_namespace: str
    category: str
    score: float
    confidence: str
    source: str
    evidence: str
    classifier_version: str = CLASSIFIER_VERSION
    taxonomy_version: str = TAXONOMY_VERSION
    embedding_model: str = EMBEDDING_MODEL


@dataclass(frozen=True)
class TaxonomyEntry:
    """Embedding-ready taxonomy category description."""

    namespace: str
    category: str
    description: str
    examples: tuple[str, ...] = ()

    @property
    def text(self) -> str:
        examples = " ".join(self.examples)
        return f"namespace={self.namespace} category={self.category}. {self.description} Examples: {examples}".strip()


TAXONOMY_ENTRIES = (
    TaxonomyEntry("work_type", "feature", "New user-visible or product capability work.", ("feat checkout flow", "add daily card endpoint")),
    TaxonomyEntry("work_type", "bug_fix", "Fixes defects, regressions, leaks, or broken behavior.", ("fix token parsing", "repair streaming abort")),
    TaxonomyEntry("work_type", "refactor", "Behavior-preserving restructuring, simplification, cleanup, or migration.", ("refactor service boundaries", "split large function", "retire old implementation")),
    TaxonomyEntry("work_type", "docs", "Documentation, plans, READMEs, specs, or written design artifacts.", ("docs add architecture note", "write session plan")),
    TaxonomyEntry("work_type", "test", "Tests, fixtures, regression coverage, or validation harnesses.", ("test scenario replay", "add regression fixture")),
    TaxonomyEntry("work_type", "infra", "Infrastructure, deployment, CI, environment, build, or operations work.", ("deploy staging", "update workflow", "terraform module")),
    TaxonomyEntry("work_type", "agent_tooling", "Agent, coding assistant, prompt, CLAUDE, AGENTS, or automation-tooling work.", ("update AGENTS.md", "add claude workflow")),
    TaxonomyEntry("quality", "risky_change", "Large, cross-cutting, security-sensitive, or low-test change that may need review.", ("large auth rewrite", "many files no tests")),
    TaxonomyEntry("component", "backend", "Server, API, service, worker, or backend domain code.", ("api handler", "service layer")),
    TaxonomyEntry("component", "frontend", "Client, UI, web app, component, page, styling, or frontend state code.", ("React component", "client route")),
    TaxonomyEntry("component", "data", "Data model, analytics, DuckDB, parquet, metrics, warehouse, or ledger work.", ("duckdb insight", "parquet schema")),
    TaxonomyEntry("component", "infra", "Deployment, environment, CI/CD, container, cloud, or infrastructure area.", ("values-prod", "deployment branch", "GitHub action")),
    TaxonomyEntry("component", "auth", "Authentication, authorization, token, permission, OAuth, or security identity area.", ("jwt token", "permission check")),
    TaxonomyEntry("component", "oracle", "Oracle, astrology, card reading, daily card, or jyotish product domain.", ("oracle adapter", "daily card lunar overlay")),
)


def _string(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value)


def _csv_values(value: Any) -> list[str]:
    text = _string(value)
    return [item.strip() for item in text.split(",") if item.strip()]


def _observed_at(row: dict[str, Any], candidates: Iterable[str]) -> Any:
    for key in candidates:
        value = row.get(key)
        if value is not None and not pd.isna(value):
            return value
    return row.get("collected_at")


def _unit_text(*parts: Any) -> str:
    return " ".join(part for part in (_string(value).strip() for value in parts) if part)


def semantic_unit_from_pr_row(row: dict[str, Any]) -> SemanticUnit:
    """Build a semantic unit from a PR row."""
    pr_number = _string(row.get("pr_number"))
    return SemanticUnit(
        kind="pr",
        unit_id=pr_number,
        org=_string(row.get("org")),
        repo=_string(row.get("repo")),
        text=_unit_text(row.get("title"), row.get("body"), row.get("labels"), row.get("head_ref"), row.get("task_id"), row.get("spec_name")),
        metadata={
            **row,
            "observed_at": _observed_at(row, ("updated_at", "created_at")),
            "paths": [],
        },
    )


def semantic_unit_from_commit_row(row: dict[str, Any]) -> SemanticUnit:
    """Build a semantic unit from a commit row."""
    paths = _csv_values(row.get("top_level_dirs")) + _csv_values(row.get("file_exts"))
    return SemanticUnit(
        kind="commit",
        unit_id=_string(row.get("sha")),
        org=_string(row.get("org")),
        repo=_string(row.get("repo")),
        text=_unit_text(
            row.get("subject"),
            row.get("body"),
            row.get("conventional_type"),
            row.get("conventional_scope"),
            row.get("activity_class"),
            row.get("branch_refs"),
            row.get("top_level_dirs"),
            row.get("file_exts"),
            row.get("task_id"),
            row.get("spec_name"),
        ),
        metadata={
            **row,
            "observed_at": _observed_at(row, ("committed_at", "authored_at")),
            "paths": paths,
        },
    )


def semantic_unit_from_branch_row(row: dict[str, Any]) -> SemanticUnit:
    """Build a semantic unit from a branch snapshot row."""
    return SemanticUnit(
        kind="branch",
        unit_id=_string(row.get("branch")),
        org=_string(row.get("org")),
        repo=_string(row.get("repo")),
        text=_unit_text(row.get("branch"), row.get("pr_title"), row.get("task_id"), row.get("spec_name")),
        metadata={
            **row,
            "observed_at": _observed_at(row, ("last_commit_at",)),
            "paths": [],
        },
    )


def semantic_units_from_rows(unit_kind: str, rows: Iterable[dict[str, Any]]) -> list[SemanticUnit]:
    """Build semantic units for a delivery-lake row collection."""
    builders = {
        "pr": semantic_unit_from_pr_row,
        "commit": semantic_unit_from_commit_row,
        "branch": semantic_unit_from_branch_row,
    }
    builder = builders[unit_kind]
    units = [builder(row) for row in rows]
    return [unit for unit in units if unit.unit_id]


def _fact(namespace: str, category: str, evidence: str, score: float = 1.0, confidence: str = "high", source: str = "rule") -> CategoryFact:
    return CategoryFact(namespace, category, score, confidence, source, evidence)


def _add_unique(facts: list[CategoryFact], fact: CategoryFact) -> None:
    key = (fact.category_namespace, fact.category)
    if key not in {(item.category_namespace, item.category) for item in facts}:
        facts.append(fact)


def _classify_work_type(unit: SemanticUnit, facts: list[CategoryFact]) -> None:
    conventional_type = _string(unit.metadata.get("conventional_type")).lower()
    if not conventional_type:
        conventional_type, _scope = parse_conventional_commit(_string(unit.metadata.get("subject") or unit.metadata.get("title")))
        conventional_type = conventional_type or ""
    activity_class = _string(unit.metadata.get("activity_class"))
    if conventional_type in WORK_TYPE_FROM_CONVENTIONAL:
        category = WORK_TYPE_FROM_CONVENTIONAL[conventional_type]
        _add_unique(facts, _fact("work_type", category, f"conventional_type={conventional_type}"))
        if category == "refactor":
            _add_unique(facts, _fact("quality", "refactoring", "conventional_type=refactor"))
        return
    if activity_class in WORK_TYPE_FROM_ACTIVITY:
        category = WORK_TYPE_FROM_ACTIVITY[activity_class]
        _add_unique(facts, _fact("work_type", category, f"activity_class={activity_class}", score=0.9))
        if category == "refactor":
            _add_unique(facts, _fact("quality", "refactoring", f"activity_class={activity_class}", score=0.9))


def _branch_name(unit: SemanticUnit) -> str:
    return _string(unit.metadata.get("branch") or unit.metadata.get("head_ref") or unit.unit_id)


def _classify_branch_role(unit: SemanticUnit, facts: list[CategoryFact]) -> None:
    if unit.kind not in {"branch", "pr"}:
        return
    branch = _branch_name(unit)
    lowered = branch.lower()
    first = lowered.split("/", 1)[0]
    if lowered in ENVIRONMENT_BRANCHES or first in ENVIRONMENT_BRANCHES:
        _add_unique(facts, _fact("branch_role", "environment", f"branch={branch}"))
    elif first in {"deploy", "deployment"} or "deployment" in lowered:
        _add_unique(facts, _fact("branch_role", "deployment", f"branch={branch}"))
    elif first in {"release", "releases"}:
        _add_unique(facts, _fact("branch_role", "release", f"branch={branch}"))
    elif first == "hotfix":
        _add_unique(facts, _fact("branch_role", "hotfix", f"branch={branch}"))
    elif first in {"dependabot", "renovate"}:
        _add_unique(facts, _fact("branch_role", "bot_generated", f"branch={branch}"))
    elif TICKET_RE.search(branch):
        _add_unique(facts, _fact("branch_role", "ticket_wip", f"branch={branch}", score=0.9))
    elif unit.kind == "branch":
        _add_unique(facts, _fact("branch_role", "feature_wip", f"branch={branch}", score=0.75, confidence="medium"))


def _classify_traceability(unit: SemanticUnit, facts: list[CategoryFact]) -> None:
    task_id = _string(unit.metadata.get("task_id"))
    spec_name = _string(unit.metadata.get("spec_name"))
    if task_id:
        _add_unique(facts, _fact("traceability", "ticket_linked", f"task_id={task_id}"))
        _add_unique(facts, _fact("ticket", task_id, "task_id", source="propagated"))
    if spec_name:
        _add_unique(facts, _fact("traceability", "spec_linked", f"spec_name={spec_name}"))
        _add_unique(facts, _fact("spec", spec_name, "spec_name", source="propagated"))
    if not task_id and not spec_name:
        _add_unique(facts, _fact("traceability", "untraced", "missing task_id/spec_name", score=0.8, confidence="medium"))


def _classify_quality_paths(unit: SemanticUnit, facts: list[CategoryFact]) -> None:
    paths = [_string(path) for path in unit.metadata.get("paths", []) if _string(path)]
    text = unit.text.lower()
    if any(is_test_path(path) for path in paths) or "test" in text:
        _add_unique(facts, _fact("quality", "test_coverage", "test path or text"))
    if any(is_generated_path(path) for path in paths) or "generated" in text:
        _add_unique(facts, _fact("quality", "generated_code", "generated/vendor path or text", score=0.9))
    if any(is_sensitive_path(path) for path in paths) or any(keyword in text for keyword in ("auth", "jwt", "token", "permission", "secret")):
        _add_unique(facts, _fact("quality", "sensitive_path", "security-sensitive path or text", score=0.9))
    if "agent_tooling" in text or ".claude" in text or ".opencode" in text or "agents.md" in text:
        _add_unique(facts, _fact("work_type", "agent_tooling", "agent tooling path or marker", score=0.9))


def _classify_components(unit: SemanticUnit, facts: list[CategoryFact]) -> None:
    text = unit.text.lower()
    for category, keywords in COMPONENT_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            _add_unique(facts, _fact("component", category, f"matched {category} keyword", score=0.8, confidence="medium"))


def classify_semantic_unit(unit: SemanticUnit) -> list[CategoryFact]:
    """Return deterministic category facts for one semantic unit."""
    facts: list[CategoryFact] = []
    _classify_work_type(unit, facts)
    _classify_branch_role(unit, facts)
    _classify_traceability(unit, facts)
    _classify_quality_paths(unit, facts)
    _classify_components(unit, facts)
    return facts


def _cosine(left: list[float], right: list[float]) -> float:
    """Return cosine similarity for two embedding vectors."""
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


def _embedding_confidence(score: float) -> str:
    if score >= 0.84:
        return "high"
    if score >= 0.76:
        return "medium"
    return "low"


def _embedding_fact(entry: TaxonomyEntry, score: float, embedding_model: str) -> CategoryFact:
    return CategoryFact(
        category_namespace=entry.namespace,
        category=entry.category,
        score=round(score, 4),
        confidence=_embedding_confidence(score),
        source="embedding",
        evidence=f"cosine={score:.3f}; taxonomy={entry.namespace}/{entry.category}",
        classifier_version=EMBEDDING_CLASSIFIER_VERSION,
        taxonomy_version=TAXONOMY_VERSION,
        embedding_model=embedding_model,
    )


def _embedding_category_facts(
    units: list[SemanticUnit],
    embedding_client: Any,
    threshold: float,
    embedding_model: str,
) -> dict[str, list[CategoryFact]]:
    """Return embedding-derived category facts keyed by unit identity."""
    taxonomy_texts = [entry.text for entry in TAXONOMY_ENTRIES]
    unit_texts = [unit.text for unit in units]
    taxonomy_results = embedding_client.embed(taxonomy_texts)
    unit_results = embedding_client.embed(unit_texts)
    taxonomy_vectors = [result.embedding for result in taxonomy_results]

    facts_by_unit: dict[str, list[CategoryFact]] = {}
    for unit, unit_result in zip(units, unit_results):
        if not unit_result.embedding:
            continue
        unit_facts: list[CategoryFact] = []
        for entry, taxonomy_vector in zip(TAXONOMY_ENTRIES, taxonomy_vectors):
            if not taxonomy_vector:
                continue
            score = _cosine(unit_result.embedding, taxonomy_vector)
            if score >= threshold:
                _add_unique(unit_facts, _embedding_fact(entry, score, embedding_model))
        facts_by_unit[f"{unit.kind}:{unit.unit_id}"] = unit_facts
    return facts_by_unit


def _semantic_facts(
    units: list[SemanticUnit],
    semantic_mode: str,
    embedding_client: Any | None,
    embedding_threshold: float,
    embedding_model: str,
) -> list[tuple[SemanticUnit, CategoryFact]]:
    """Classify units with deterministic rules and optional embedding candidates."""
    rule_enabled = semantic_mode in {"rules", "hybrid"}
    embedding_enabled = semantic_mode == "hybrid" and embedding_client is not None
    embedding_facts = _embedding_category_facts(units, embedding_client, embedding_threshold, embedding_model) if embedding_enabled else {}

    rows: list[tuple[SemanticUnit, CategoryFact]] = []
    for unit in units:
        facts = classify_semantic_unit(unit) if rule_enabled else []
        for fact in embedding_facts.get(f"{unit.kind}:{unit.unit_id}", []):
            _add_unique(facts, fact)
        rows.extend((unit, fact) for fact in facts)
    return rows


def _timestamp_partition(value: Any) -> tuple[int | None, int | None]:
    ts = pd.to_datetime(value) if value is not None and not pd.isna(value) else None
    return (ts.year, ts.month) if ts is not None else (None, None)


def _category_row(unit: SemanticUnit, fact: CategoryFact, classified_at: pd.Timestamp) -> dict[str, Any]:
    observed_at = unit.metadata.get("observed_at")
    year, month = _timestamp_partition(observed_at or classified_at)
    return {
        "org": unit.org,
        "repo": unit.repo,
        "year": year,
        "month": month,
        "unit_kind": unit.kind,
        "unit_id": unit.unit_id,
        "category_namespace": fact.category_namespace,
        "category": fact.category,
        "score": fact.score,
        "confidence": fact.confidence,
        "source": fact.source,
        "evidence": fact.evidence,
        "classifier_version": fact.classifier_version,
        "taxonomy_version": fact.taxonomy_version,
        "embedding_model": fact.embedding_model,
        "classified_at": classified_at,
        "observed_at": observed_at,
    }


def classify_semantic_units(
    units: Iterable[SemanticUnit],
    semantic_mode: str = "rules",
    embedding_client: Any | None = None,
    embedding_threshold: float = DEFAULT_EMBEDDING_THRESHOLD,
    embedding_model: str = EMBEDDING_MODEL,
) -> list[dict[str, Any]]:
    """Classify units into durable semantic category fact rows."""
    unit_list = list(units)
    classified_at = pd.Timestamp(datetime.now(timezone.utc))
    return [
        _category_row(unit, fact, classified_at)
        for unit, fact in _semantic_facts(unit_list, semantic_mode, embedding_client, embedding_threshold, embedding_model)
    ]


def classify_delivery_lake_rows(
    pr_rows: Iterable[dict[str, Any]] = (),
    commit_rows: Iterable[dict[str, Any]] = (),
    branch_rows: Iterable[dict[str, Any]] = (),
    semantic_mode: str = "rules",
    embedding_client: Any | None = None,
    embedding_threshold: float = DEFAULT_EMBEDDING_THRESHOLD,
    embedding_model: str = EMBEDDING_MODEL,
) -> list[dict[str, Any]]:
    """Classify PR, commit, and branch rows into semantic category facts."""
    units = []
    units.extend(semantic_units_from_rows("pr", pr_rows))
    units.extend(semantic_units_from_rows("commit", commit_rows))
    units.extend(semantic_units_from_rows("branch", branch_rows))
    return classify_semantic_units(
        units,
        semantic_mode=semantic_mode,
        embedding_client=embedding_client,
        embedding_threshold=embedding_threshold,
        embedding_model=embedding_model,
    )
