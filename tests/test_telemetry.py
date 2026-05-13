import json

import pytest

from pr_metrics.telemetry import RunTelemetry


def test_run_telemetry_writes_jsonl_and_summary(tmp_path):
    telemetry = RunTelemetry(tmp_path, run_id="run-1")

    with telemetry.span("phase.one", org="Acme", repo="backend"):
        pass
    telemetry.record("phase.rows", rows=3, status="ok")

    events = [json.loads(line) for line in telemetry.path.read_text().splitlines()]

    assert telemetry.path == tmp_path / "telemetry" / "runs" / "run-1.jsonl"
    assert events[0]["phase"] == "phase.one"
    assert events[0]["status"] == "ok"
    assert events[0]["org"] == "Acme"
    assert events[1]["rows"] == 3
    assert telemetry.summary()[0]["phase"] == "phase.one"


def test_run_telemetry_records_errors(tmp_path):
    telemetry = RunTelemetry(tmp_path, run_id="run-err")

    with pytest.raises(ValueError):
        with telemetry.span("phase.bad"):
            raise ValueError("boom")

    event = json.loads(telemetry.path.read_text().splitlines()[0])
    assert event["status"] == "error"
    assert event["error_type"] == "ValueError"


def test_disabled_telemetry_does_not_create_file(tmp_path):
    telemetry = RunTelemetry(tmp_path, enabled=False, run_id="off")

    with telemetry.span("phase.off"):
        pass

    assert not telemetry.path.exists()
    assert telemetry.summary() == []
