"""Checkpoint store — CK-1..4 scaffold (gates-as-checkpoints).

At each gate the store persists: gate outcome, run manifest (pins/ids), sealed stage
outputs, per-analyst counters {validation retries, crash restarts}, running effective-N
(CK-1). Resume loads the LAST PASSED gate and re-executes nothing before it (CK-2);
counters survive resume so a retry-once can never become retry-twice via a crash.
Crash restarts are bounded <=2 per analyst per run, then exclusion with a mechanical
reason (CK-3) — no FC class is fabricated (D19 held). Window validity is checked by the
T-bound hook whose clock authority is Talon (CK-4); the hook fails closed when the
authority is not configured.

Checkpoint rows are append-only and immutable.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

CRASH_RESTART_LIMIT = 2
EXCLUSION_REASON_CRASH_LIMIT = "crash_restart_limit"


def _ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class CheckpointStore:
    def __init__(self, path: str | Path, run_id: str):
        self.path = Path(path)
        self.run_id = run_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")
        self._clock_authority_token: str | None = None

    def _append(self, row: dict[str, Any]) -> None:
        row_id = uuid.uuid4().hex
        full = {"row_id": row_id, "run_id": self.run_id, "ts": _ts(), **row}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(full, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n")

    def checkpoint_gate(
        self,
        gate: str,
        run_manifest: dict[str, Any],
        sealed_stage_outputs: list[str],
        analyst_counters: dict[str, dict[str, Any]],
        effective_n: int,
    ) -> dict[str, Any]:
        row = {
            "row_type": "gate_checkpoint",
            "gate": gate,
            "passed": True,
            "run_manifest": run_manifest,
            "sealed_stage_outputs": sealed_stage_outputs,
            "analyst_counters": analyst_counters,
            "effective_n": effective_n,
        }
        self._append(row)
        return {"gate": gate, "persisted": True}

    def record_crash_restart(self, analyst: str, analyst_counters: dict[str, dict[str, Any]]) -> dict[str, Any]:
        c = analyst_counters.setdefault(analyst, {"validation_retries": 0, "crash_restarts": 0, "excluded": None})
        c["crash_restarts"] += 1
        outcome = "ok"
        if c["crash_restarts"] > CRASH_RESTART_LIMIT:
            c["excluded"] = EXCLUSION_REASON_CRASH_LIMIT
            outcome = "excluded"
        self._append(
            {
                "row_type": "crash_event",
                "analyst": analyst,
                "crash_restarts": c["crash_restarts"],
                "outcome": outcome,
            }
        )
        return {"analyst": analyst, "crash_restarts": c["crash_restarts"], "outcome": outcome}

    def record_validation_retry(self, analyst: str, analyst_counters: dict[str, dict[str, Any]]) -> None:
        c = analyst_counters.setdefault(analyst, {"validation_retries": 0, "crash_restarts": 0, "excluded": None})
        c["validation_retries"] += 1

    def last_passed_gate(self) -> dict[str, Any] | None:
        rows = self.rows()
        for row in reversed(rows):
            if row.get("row_type") == "gate_checkpoint" and row.get("passed"):
                return row
        return None

    def resume_state(self) -> dict[str, Any] | None:
        return self.last_passed_gate()

    def rows(self) -> list[dict[str, Any]]:
        out = []
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

    # ---- CK-4 T-bound hook (clock authority = Talon) ----
    def authorize_clock(self, token: str) -> None:
        self._clock_authority_token = token

    def check_t_bound(self, now: float, window_close: float) -> dict[str, str]:
        if self._clock_authority_token is None:
            return {"status": "unconfigured", "detail": "clock authority not configured; fail closed (CK-4)"}
        if now > window_close:
            return {"status": "exhausted", "detail": "resume window expired; honest failure (I7)"}
        return {"status": "ok", "detail": "within window"}

    def _reset_file(self) -> None:
        self.path.write_text("", encoding="utf-8")
