"""Minimal fixture store surface for the IF-2 choke-point demo (read-only by assembler).

Distinct immutable items keyed by (entity, attribute, snapshot-time) — a change is a NEW
item, never a mutation (DA-2). Content is fixture text only; nothing here decides what
may enter a package (that boundary is IF-2/DA-4 and belongs to later wiring).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path


class MockEvidenceStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")
        self._items: list[dict] = []

    def add_item(self, entity: str, attribute: str, snapshot_time: str, value: dict) -> dict:
        item = {
            "item_id": f"{entity}:{attribute}:{snapshot_time}",
            "entity": entity,
            "attribute": attribute,
            "snapshot_time": snapshot_time,
            "value": value,
            "row_id": uuid.uuid4().hex,
        }
        self._items.append(item)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(item, sort_keys=True) + "\n")
        return item

    def read_items(self, lane: str, request_ids: list[str]) -> list[dict]:
        wanted = set(request_ids)
        return [it for it in self._items if it["item_id"] in wanted]

    def framing_snapshot(self, slate_id: str, run_id: str) -> dict:
        return {"slate_id": slate_id, "run_id": run_id, "ref": f"framing-instance:{slate_id}:{run_id}", "content": "fixture-only"}
