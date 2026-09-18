"""WS4 — replay surface (P20 §5.2). Phase 3 provides the recorded-response reader
only; full `--replay` execution is Phase 6 (integration, T-06).

REGISTERED REPLAY/HASH IMPLICATION (LC-2 provenance note, 2026-09-17):
    Artifact hashes produced by `ecai.hashing.sha256_json` include `produced_at`,
    so they are RUN-SCOPED — two executions of the same inputs differ in hash.
    Phase 3 does NOT redefine replay semantics and does NOT introduce a new digest
    scheme. The integration phase (Phase 6) must decide the replay hash policy
    (e.g. hash excluding volatile fields, or a documented timestamp-normalization
    rule) so that `--replay` byte-identity (T-06) is well-defined. Until then,
    replay compares recorded raw responses, not re-derived artifact hashes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPLAY_HASH_IMPLICATION = (
    "artifact hashes include produced_at -> run-scoped; replay hash policy deferred "
    "to Phase 6 (see module docstring)"
)


class ReplayNotAvailable(RuntimeError):
    """Full replay is a Phase 6 deliverable; Phase 3 exposes recorded responses only."""


def list_raw_responses(run_dir: str | Path) -> list[Path]:
    raw_dir = Path(run_dir) / "raw"
    if not raw_dir.is_dir():
        return []
    return sorted(raw_dir.glob("*.json"))


def load_raw_response(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def find_raw_response(
    run_dir: str | Path, *, stage: str, persona: str | None = None
) -> Path | None:
    persona_part = persona or "none"
    for path in list_raw_responses(run_dir):
        if path.name.startswith(f"{stage}_{persona_part}_"):
            return path
    return None


def replay_run(*_args: Any, **_kwargs: Any) -> Any:
    raise ReplayNotAvailable(
        "full replay is Phase 6 (integration); Phase 3 records raw responses only"
    )
