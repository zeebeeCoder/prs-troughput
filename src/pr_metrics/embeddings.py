"""Lean embedding clients for semantic enrichment."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import time
from typing import Any
from urllib import error, request

FIREWORKS_EMBEDDINGS_URL = "https://api.fireworks.ai/inference/v1/embeddings"
DEFAULT_FIREWORKS_MODEL = "nomic-ai/nomic-embed-text-v1.5"
DEFAULT_FIREWORKS_DIMENSIONS = 768
DEFAULT_SEMANTIC_CONFIG = Path.home() / ".config" / "semantic-cli" / "config.json"
MAX_RETRIES = 3
BASE_RETRY_S = 1.0
MAX_RETRY_S = 8.0


@dataclass(frozen=True)
class EmbeddingResult:
    """Embedding API result for one input text."""

    text: str
    embedding: list[float] | None
    tokens: int = 0
    error: str | None = None


class FireworksEmbeddingError(Exception):
    """HTTP/API error from Fireworks embeddings."""

    def __init__(self, status: int, message: str, retry_after_s: float | None = None):
        super().__init__(message)
        self.status = status
        self.retry_after_s = retry_after_s


def _retry_after_s(headers) -> float | None:
    value = headers.get("retry-after")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def _retry_delay_s(attempt: int, retry_after_s: float | None = None) -> float:
    if retry_after_s is not None:
        return max(retry_after_s, BASE_RETRY_S)
    return min(BASE_RETRY_S * (2 ** attempt), MAX_RETRY_S)


def resolve_fireworks_api_key(config_path: str | Path | None = None) -> str | None:
    """Resolve Fireworks API key from environment or semantic-cli config without printing it."""
    env_key = os.environ.get("FIREWORKS_API_KEY")
    if env_key:
        return env_key

    path = Path(config_path) if config_path else DEFAULT_SEMANTIC_CONFIG
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None

    value = data.get("fireworks_api_key") if isinstance(data, dict) else None
    return value if isinstance(value, str) and value else None


class FireworksEmbeddingClient:
    """Small Fireworks embeddings API client with retry and batch splitting."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_FIREWORKS_MODEL,
        dimensions: int | None = DEFAULT_FIREWORKS_DIMENSIONS,
        batch_size: int = 32,
        timeout_s: int = 30,
    ):
        self.api_key = api_key
        self.model = model
        self.dimensions = dimensions
        self.batch_size = batch_size
        self.timeout_s = timeout_s
        self.total_tokens = 0

    def embed(self, texts: list[str]) -> list[EmbeddingResult]:
        """Embed texts, preserving input order and returning non-fatal error results."""
        results: list[EmbeddingResult] = []
        for start in range(0, len(texts), self.batch_size):
            results.extend(self._embed_with_retry(texts[start:start + self.batch_size]))
        return results

    def _embed_with_retry(self, texts: list[str], attempt: int = 0) -> list[EmbeddingResult]:
        if not texts:
            return []
        try:
            return self._process_response(texts, self._call_api(texts))
        except FireworksEmbeddingError as exc:
            if exc.status == 429 or exc.status >= 500:
                if attempt < MAX_RETRIES:
                    time.sleep(_retry_delay_s(attempt, exc.retry_after_s))
                    return self._embed_with_retry(texts, attempt + 1)
                if len(texts) > 1:
                    midpoint = max(1, len(texts) // 2)
                    return self._embed_with_retry(texts[:midpoint]) + self._embed_with_retry(texts[midpoint:])
            return _error_results(texts, str(exc))
        except Exception as exc:  # non-fatal: semantic rules should still persist
            return _error_results(texts, str(exc))

    def _call_api(self, texts: list[str]) -> dict[str, Any]:
        payload: dict[str, Any] = {"input": texts, "model": self.model}
        if self.dimensions:
            payload["dimensions"] = self.dimensions

        req = request.Request(
            FIREWORKS_EMBEDDINGS_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                # Fireworks sits behind Cloudflare; Python's default urllib UA can be rejected.
                "User-Agent": "pr-metrics/0.1 (+https://github.com/zeebeeCoder/prs-troughput)",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout_s) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise FireworksEmbeddingError(exc.code, f"Fireworks HTTP {exc.code}: {body}", _retry_after_s(exc.headers)) from exc

    def _process_response(self, texts: list[str], response: dict[str, Any]) -> list[EmbeddingResult]:
        usage = response.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or usage.get("total_tokens") or 0)
        self.total_tokens += prompt_tokens
        tokens_per_item = int((prompt_tokens + len(texts) - 1) / len(texts)) if texts else 0

        by_index = {
            int(item.get("index", index)): item.get("embedding")
            for index, item in enumerate(response.get("data") or [])
        }
        return [
            EmbeddingResult(
                text=text,
                embedding=by_index.get(index),
                tokens=tokens_per_item,
                error=None if by_index.get(index) is not None else f"missing embedding for index {index}",
            )
            for index, text in enumerate(texts)
        ]


def _error_results(texts: list[str], message: str) -> list[EmbeddingResult]:
    return [EmbeddingResult(text=text, embedding=None, tokens=0, error=message) for text in texts]


def create_fireworks_embedding_client(
    config_path: str | Path | None = None,
    model: str = DEFAULT_FIREWORKS_MODEL,
    dimensions: int | None = DEFAULT_FIREWORKS_DIMENSIONS,
    batch_size: int = 32,
) -> FireworksEmbeddingClient | None:
    """Create a Fireworks client when a key is available; otherwise return None."""
    api_key = resolve_fireworks_api_key(config_path)
    if not api_key:
        return None
    return FireworksEmbeddingClient(api_key, model=model, dimensions=dimensions, batch_size=batch_size)
