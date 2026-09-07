"""L3 fallback scaffold — FB-1..3 (registry-eligibility + automatic switchover).

FB-2 switchover is automatic AT the provider-abstraction layer on execution failure and
is whole-run granularity: after a switch the run stays on the fallback. FB-1 eligibility
is structural (a registered entry whose capability set includes the L3-fallback role);
pre-pilot approval is an OUTSIDE surface (Talon/Don) and is never assumed here. FB-3
records every switchover as {primary, fallback, trigger, ts, affected} for provenance +
integrity report. Both primary and fallback failed => blocked, never bypassed (I5).

No live provider execution: primaries/fallbacks are W1 mocks.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

FALLBACK_ROLE = "l3_fallback"


def _ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def registry_entry_eligible(entry: dict[str, Any] | None, primary_model: str) -> dict[str, Any]:
    """FB-1 structural eligibility. Approval (pilot) is OUTSIDE — never asserted."""
    if entry is None:
        return {"eligible": False, "reason": f"no registry entry for {primary_model}", "approval_assumed": False}
    caps = entry.get("capability_classes", [])
    if FALLBACK_ROLE not in caps:
        return {"eligible": False, "reason": f"{primary_model} lacks {FALLBACK_ROLE} capability", "approval_assumed": False}
    return {"eligible": True, "reason": "role-capable registry entry present", "approval_assumed": False}


@dataclass
class FallbackProvider:
    """Wraps primary+fallback W1 providers; automatic whole-run switchover (FB-2)."""

    primary: Any
    fallback: Any
    switch_events: list[dict[str, Any]] = field(default_factory=list)
    _active: str = "primary"

    def _record_switch(self, call: Any, trigger: str) -> None:
        self.switch_events.append(
            {
                "primary": getattr(self.primary, "name", type(self.primary).__name__),
                "fallback": getattr(self.fallback, "name", type(self.fallback).__name__),
                "trigger": trigger,
                "ts": _ts(),
                "affected": {"run_id": call.run_id, "layer": call.layer},
            }
        )

    def execute(self, call: Any) -> dict[str, Any]:
        active = self.primary if self._active == "primary" else self.fallback
        res = active.execute(call)
        if res["status"] == "ok":
            return res
        if self._active == "primary":
            self._active = "fallback"
            self._record_switch(call, trigger="primary_execution_failure")
            fb = self.fallback.execute(call)
            if fb["status"] == "failed":
                return {"status": "blocked", "reason": "both primary and fallback failed; entries blocked, never bypassed (I5)", "switch_events": self.switch_events}
            return fb
        return {"status": "blocked", "reason": "fallback failed after switchover; entries blocked (I5)", "switch_events": self.switch_events}
