"""Observability emit-points (A0 OB-2/OB-5 shape). Emitted events carry OB-2 granularity
keys: component / run / layer / source / analyst slot, plus per-event metrics. In Wave 1 the
events are structural (call outcomes, token counts); OB-5 content metrics (contamination,
hallucination by layer, etc.) are Wave 2+ surfaces and are NOT fabricated here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class Emitter:
    """Collects emit-point events. In-process (no external sink) for the mock run, so the
    run is fully replayable and requires no network. Events are append-only JSONL."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self._events: list[dict[str, Any]] = []
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self.path.exists():
                self.path.write_text("", encoding="utf-8")

    def emit(self, event: dict[str, Any]) -> None:
        self._events.append(event)
        if self.path:
            import json

            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=True, sort_keys=True) + "\n")

    def all(self) -> list[dict[str, Any]]:
        return list(self._events)
