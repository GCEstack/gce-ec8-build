"""IF-2 evidence-package choke point — SHAPE only (scaffold).

A single assembly function `Assembler.assemble_package` is the ONLY path from a lane
request (store reads) to a package envelope (I1). Wire contract shape only: the envelope
carries structural slots (slate ref, framing ref, cumulative item list, request_status
map, disclosure line) with NO content semantics implemented — filling a request,
market policy, and status classification are Wave-2-blocked surfaces routed to
Kimi/Chiave, and any attempt to exercise them fails closed.

Envelope construction is module-private; any other production path to an envelope is a
bypass, detected and counted. All store reads during assembly are attributed to the
choke point so a package audit can reconstruct every delivered item later (G6 audit
surface, implemented in later waves).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol


class EvidenceStore(Protocol):
    """Read-only store surface the choke point is allowed to touch (DA-4)."""

    def read_items(self, lane: str, request_ids: list[str]) -> list[dict[str, Any]]: ...

    def framing_snapshot(self, slate_id: str, run_id: str) -> dict[str, Any]: ...


@dataclass
class PackageEnvelope:
    slate_id: str
    run_id: str
    lane: str
    framing_snapshot_ref: dict[str, Any]
    cumulative_items: list[dict[str, Any]]
    request_status_map: dict[str, Any]
    disclosure_line: str
    assembled_by: str = "IF2_CHOKEPOINT"

    def to_row(self) -> dict[str, Any]:
        return {
            "kind": "package",
            "slate_id": self.slate_id,
            "run_id": self.run_id,
            "lane": self.lane,
            "framing_snapshot_ref": self.framing_snapshot_ref,
            "cumulative_items": self.cumulative_items,
            "request_status_map": self.request_status_map,
            "disclosure_line": self.disclosure_line,
            "assembled_by": self.assembled_by,
        }


@dataclass
class Assembler:
    """Choke point. `assemble_package` is the only envelope-producing public entry."""

    store: EvidenceStore
    assembly_calls: int = 0
    bypass_detected: int = 0
    _read_trace: list[str] = field(default_factory=list, repr=False)

    def assemble_package(
        self,
        slate_id: str,
        run_id: str,
        lane: str,
        request_ids: list[str],
        request_statuses: dict[str, Any] | None = None,
    ) -> PackageEnvelope:
        """Single assembly function. All store-read-to-package paths route through here."""
        self.assembly_calls += 1
        snapshot = self.store.framing_snapshot(slate_id, run_id)
        items = self.store.read_items(lane, request_ids)
        self._read_trace.append(json.dumps({"lane": lane, "request_ids": sorted(request_ids)}, sort_keys=True))
        status_map = dict(request_statuses or {})
        return PackageEnvelope(
            slate_id=slate_id,
            run_id=run_id,
            lane=lane,
            framing_snapshot_ref=snapshot,
            cumulative_items=items,
            request_status_map=status_map,
            disclosure_line="cumulative requested-item delivery; nothing else, ever (I1)",
        )

    def track_bypass(self, reason: str) -> None:
        """Detector hook: a bypass attempt is counted, never silently allowed."""
        self.bypass_detected += 1
        self._read_trace.append(json.dumps({"bypass": reason}, sort_keys=True))
