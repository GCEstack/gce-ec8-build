"""WS4 — provenance logging + raw-response retention (P20 §5.2).

* `provenance.jsonl` is append-only: one JSON record per invocation. Nothing is
  ever rewritten.
* Every raw Converse response (unparsed body + request metadata) is written under
  `runs/<run_id>/raw/<stage>_<persona>_<ts>.json` BEFORE parsing.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..hashing import sha256_json

RAW_MARKER = "ecai/raw_response/1.0"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


class ProvenanceLog:
    """Append-only JSONL provenance log for a run."""

    def __init__(self, run_dir: str | Path):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.run_dir / "provenance.jsonl"

    def append(self, record: dict[str, Any]) -> dict[str, Any]:
        entry = {"schema_id": "ecai/provenance_record/1.0", **record}
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=True, sort_keys=True) + "\n")
        return entry

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        return [
            json.loads(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def record_substitutions(
        self, substitutions: list[dict[str, Any]], *, manifest_hash: str
    ) -> list[dict[str, Any]]:
        written = []
        for sub in substitutions:
            written.append(
                self.append(
                    {
                        "kind": "substitution",
                        "manifest_hash": manifest_hash,
                        **sub,
                    }
                )
            )
        return written


class RawRetention:
    """Writes raw Converse responses to disk before any parsing."""

    def __init__(self, run_dir: str | Path):
        self.run_dir = Path(run_dir)
        self.raw_dir = self.run_dir / "raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def store(
        self,
        *,
        stage: str,
        persona: str | None,
        model_id: str,
        request: dict[str, Any],
        response: Any,
        latency_ms: int,
        retries: int,
    ) -> Path:
        stamp = _utc_stamp()
        persona_part = persona or "none"
        path = self.raw_dir / f"{stage}_{persona_part}_{stamp}.json"
        payload = {
            "schema_id": RAW_MARKER,
            "stage": stage,
            "persona": persona,
            "model_id": model_id,
            "request_hash": sha256_json(request),
            "response_hash": sha256_json(response),
            "latency_ms": latency_ms,
            "retries": retries,
            "retained_at": stamp,
            "request": request,
            "response": response,
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8"
        )
        return path
