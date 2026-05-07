import json

from pr_metrics.embeddings import FireworksEmbeddingClient, resolve_fireworks_api_key


def test_resolve_fireworks_api_key_prefers_env(monkeypatch, tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"fireworks_api_key": "from-config"}))
    monkeypatch.setenv("FIREWORKS_API_KEY", "from-env")

    assert resolve_fireworks_api_key(config) == "from-env"


def test_resolve_fireworks_api_key_reads_semantic_cli_config(monkeypatch, tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"fireworks_api_key": "from-config"}))
    monkeypatch.delenv("FIREWORKS_API_KEY", raising=False)

    assert resolve_fireworks_api_key(config) == "from-config"


def test_fireworks_client_processes_indexed_response_order():
    client = FireworksEmbeddingClient("secret", batch_size=10)
    response = {
        "data": [
            {"index": 1, "embedding": [0.0, 1.0]},
            {"index": 0, "embedding": [1.0, 0.0]},
        ],
        "usage": {"prompt_tokens": 5},
    }

    results = client._process_response(["a", "b"], response)

    assert [result.embedding for result in results] == [[1.0, 0.0], [0.0, 1.0]]
    assert [result.tokens for result in results] == [3, 3]
    assert client.total_tokens == 5
