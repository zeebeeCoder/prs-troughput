"""Lightweight JSONL telemetry for collection runs."""

from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


class RunTelemetry:
    """Append-only per-run JSONL telemetry.

    The recorder is intentionally dependency-free and thread-safe so repo-level
    extraction workers can write phase timings without coordinating through the
    main thread.
    """

    def __init__(self, output_dir: str | os.PathLike[str], *, enabled: bool = True, run_id: str | None = None):
        self.enabled = enabled
        self.run_id = run_id or self._new_run_id()
        self.path = Path(output_dir) / "telemetry" / "runs" / f"{self.run_id}.jsonl"
        self._lock = threading.Lock()
        self._phase_totals: dict[str, dict[str, float | int]] = {}
        if self.enabled:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def span(self, phase: str, **fields: Any) -> Iterator[None]:
        """Record a timed span, marking status as ok/error."""
        started = time.perf_counter()
        try:
            yield
        except Exception as exc:
            self.record(
                phase,
                elapsed_ms=(time.perf_counter() - started) * 1000,
                status="error",
                error_type=type(exc).__name__,
                error=str(exc),
                **fields,
            )
            raise
        else:
            self.record(
                phase,
                elapsed_ms=(time.perf_counter() - started) * 1000,
                status="ok",
                **fields,
            )

    def record(self, phase: str, **fields: Any) -> None:
        """Append one event to the JSONL file and update in-memory totals."""
        if not self.enabled:
            return
        event = {
            "run_id": self.run_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "phase": phase,
            **fields,
        }
        elapsed_ms = float(fields.get("elapsed_ms") or 0)
        with self._lock:
            total = self._phase_totals.setdefault(phase, {"count": 0, "elapsed_ms": 0.0})
            total["count"] = int(total["count"]) + 1
            total["elapsed_ms"] = float(total["elapsed_ms"]) + elapsed_ms
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, default=str, sort_keys=True) + "\n")

    def summary(self) -> list[dict[str, float | int | str]]:
        """Return aggregate timings sorted by descending elapsed time."""
        rows = [
            {"phase": phase, "count": values["count"], "elapsed_ms": values["elapsed_ms"]}
            for phase, values in self._phase_totals.items()
        ]
        return sorted(rows, key=lambda row: float(row["elapsed_ms"]), reverse=True)

    @staticmethod
    def _new_run_id() -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return f"{stamp}-{os.getpid()}"
