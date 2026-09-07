"""Session-ID continuity plumbing (EX-3 / CD-4 scaffold).

One session per analyst slot per run across Stages 1..3 (two provider requests, one
session); inter-run contexts are always fresh. A machine-check hook verifies the
recorded session assignments and reports any violation: an intra-run break or an
inter-run reuse of a session id. The hook is deterministic code — no runtime judgment.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


def new_session_id() -> str:
    return "S-" + uuid.uuid4().hex


@dataclass
class SessionRecord:
    run_id: str
    slot: str
    stage: str
    session_id: str
    opened_at: str = ""


class SessionRegistry:
    """Assigns and records session ids. Runs are independent; a session never spans runs."""

    def __init__(self):
        self._records: list[SessionRecord] = []
        self._active_sessions: dict[str, str] = {}

    def open(self, run_id: str, slot: str, stage: str) -> str:
        key = f"{run_id}|{slot}"
        existing = self._active_sessions.get(key)
        if existing is None:
            existing = new_session_id()
            self._active_sessions[key] = existing
        record = SessionRecord(run_id=run_id, slot=slot, stage=stage, session_id=existing)
        self._records.append(record)
        return existing

    def record(self, record: SessionRecord) -> None:
        self._records.append(record)

    def records(self) -> list[SessionRecord]:
        return list(self._records)


def verify_session_continuity(records: list[SessionRecord]) -> list[dict[str, Any]]:
    """Machine-check (CD-4): intra-run Stage 1/3 share a session id; inter-run never do.

    Returns a list of violations; an empty list means continuity held. A Stage 1 and a
    Stage 3 record for the same (run, slot) MUST share a session id, and no session id
    may appear under two different run ids.
    """
    violations: list[dict[str, Any]] = []
    by_run_slot: dict[tuple[str, str], dict[str, str]] = {}
    session_to_run: dict[str, str] = {}
    for rec in records:
        if rec.session_id in session_to_run and session_to_run[rec.session_id] != rec.run_id:
            violations.append(
                {
                    "kind": "inter_run_reuse",
                    "session_id": rec.session_id,
                    "run_ids": sorted({session_to_run[rec.session_id], rec.run_id}),
                }
            )
        session_to_run[rec.session_id] = rec.run_id
        key = (rec.run_id, rec.slot)
        by_run_slot.setdefault(key, {})[rec.stage] = rec.session_id

    for (run_id, slot), stages in by_run_slot.items():
        if "Stage1" in stages and "Stage3" in stages and stages["Stage1"] != stages["Stage3"]:
            violations.append(
                {"kind": "intra_run_break", "run_id": run_id, "slot": slot, "stages": stages}
            )
    return violations
