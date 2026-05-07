# Embedding Semantic Enrichment

Embedding enrichment is an optional second pass over the deterministic semantic category spine.

Default semantic classification remains rules-only and requires no API calls:

```bash
uv run pr-metrics --org your-org --repo backend-api --classify-semantics
```

Hybrid mode adds embedding-derived candidate labels:

```bash
uv run pr-metrics --org your-org --repo backend-api \
  --classify-semantics \
  --semantic-mode hybrid
```

## Provider

The first provider is Fireworks AI embeddings:

- endpoint: `https://api.fireworks.ai/inference/v1/embeddings`
- default model: `nomic-ai/nomic-embed-text-v1.5`
- default dimensions: `768`

API key resolution order:

1. `FIREWORKS_API_KEY` environment variable
2. `~/.config/semantic-cli/config.json` field `fireworks_api_key`
3. optional `--embedding-config <path>` override

The key is never written to parquet or logs.

## Classification behavior

Hybrid mode embeds:

- taxonomy category descriptions/examples
- semantic unit envelopes for PRs, commits, and branches

It then computes cosine similarity in Python and persists candidate labels above `--embedding-threshold` into `semantic_categories`.

Hybrid mode also persists raw unit vectors into:

```text
output/ledger/semantic_embeddings/
```

The durable embedding grain is:

```text
(org, repo, unit_kind, unit_id, text_hash, embedding_model)
```

Rows include the semantic envelope text, vector, dimensions, tokens, error, observed timestamp, and embedded timestamp.

Embedding facts use:

```text
source=embedding
classifier_version=embedding-sim-v1
embedding_model=nomic-ai/nomic-embed-text-v1.5
score=<cosine>
confidence=low|medium|high
evidence="cosine=0.812; taxonomy=work_type/refactor"
```

Deterministic rule labels are kept as the spine. Embedding labels are additive candidates and do not replace rule/propagated labels.

## DuckDB vector queries

Vectors are stored as DuckDB list values in parquet, so they can be queried directly with DuckDB's list similarity functions:

```sql
SELECT
  unit_kind,
  unit_id,
  list_cosine_similarity(embedding, [1.0, 0.0, 0.0]) AS score,
  text
FROM semantic_embeddings_latest
WHERE unit_kind = 'commit'
  AND embedding IS NOT NULL
ORDER BY score DESC
LIMIT 20;
```

Use `semantic_embedding_coverage` to verify vector persistence and API errors:

```bash
uv run pr-metrics --org your-org --repo backend-api --insight semantic_embedding_coverage --days 30
```

## Why no DuckDB vector extension yet

For v1, Python computes taxonomy classification similarity directly because the taxonomy is small. Raw vectors are still persisted and queryable through DuckDB list functions.

A later vector-search slice can add a DuckDB VSS index once we need indexed nearest-neighbor search over many historical units.
