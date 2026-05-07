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

## Why no DuckDB vector extension yet

For v1, Python computes similarity directly because the taxonomy is small and the goal is category enrichment, not vector search. DuckDB remains the parquet/query layer.

A later vector-search slice can add a `semantic_embeddings` dataset or DuckDB VSS index once we need nearest-neighbor search over many historical units.
