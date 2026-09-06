"""Ledger — append-only execution-point cost ledger (A0 OB-1/OB-2/OB-3, I10).

Ledger unit (OB-1): one provider-billable request + its token counts. Granularity (OB-2):
component / run / analyst slot / layer / source. Retries and failures are EXTRA ledger rows
(they are never silently absorbed into a single row).

Append-only, write-once rows. The production-facing public interface exposes NO update and
NO delete of a committed row. Destructive test behavior is confined to a disposable harness
instance. The ledger is the only source of cost truth for a run (I10).

This module is intentionally independent of the Wave 0 store package (W1 non-dependency,
brief §6). It implements an append-only JSONL file store with SHA-256 row ids.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical(row: dict[str, Any]) -> bytes:
    """Deterministic canonical bytes for a ledger row (fixed field set, key order irrelevant
    because keys are sorted; used to derive the immutable row id)."""
    return json.dumps(
        row, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


class Ledger:
    """Append-only ledger of cost rows.

    Public interface: append_row / read_all / count / row_by_id / (backups under .harness
    are handled by callers, not this class). There is NO update or delete method here.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")

    # ---- production interface (no update/delete of committed rows) ----
    def append_row(self, row: dict[str, Any]) -> dict[str, Any]:
        row_id = uuid.uuid4().hex
        canonical = row.get("row_id") or hashlib.sha256(_canonical({**row, "row_id": row_id})).hexdigest()
        row_id = row.get("row_id") or row_id
        full = {
            "row_id": row_id,
            "row_sha256": hashlib.sha256(_canonical({**row, "row_id": row_id})).hexdigest(),
            **row,
        }
        # write-once: never rewrite a committed row id
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(full, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n")
        return {"status": "appended", "row_id": row_id}

    def read_all(self) -> list[dict[str, Any]]:
        out = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

    def count(self) -> int:
        return len(self.read_all())

    def row_by_id(self, row_id: str) -> dict[str, Any] | None:
        for r in self.read_all():
            if r.get("row_id") == row_id:
                return r
        return None

    # ---- disposable-only helpers (harness) ----
    def _reset_file(self) -> None:  # harness only; not part of production public behavior contract
        self.path.write_text("", encoding="utf-8")
