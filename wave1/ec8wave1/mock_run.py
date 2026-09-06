"""Mock orchestration run — 1/26/26 reference topology (53 call points), zero live traffic.

Cadence (M / A0 OB-4): Overnight 1 · Morning 26 · PreGame 26 = 53 provider call points.
Each call point = one logical provider call. The MockProvider meters each attempt into the
ledger at the execution point (OB-3) and emits observability. Injected transient failures
demonstrate retries (extra ledger rows); one injected terminal failure demonstrates a
failed ledger row. This run makes NO network call and spends $0.

The orchestration layer (this module) only ASSEMBLES call points and drives them through the
provider abstraction; it does NOT meter or emit — proving the meter lives in the provider
(no-retrofit). See `demo_no_retrofit` in the evidence run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ec8wave1.ledger import Ledger
from ec8wave1.provider import MockProvider, ProviderCall
from ec8wave1.observability import Emitter

# 1/26/26 topology labels (fixture / reference only).
OVERNIGHT_COUNT = 1
MORNING_COUNT = 26
PREGAME_COUNT = 26
TOTAL_CALL_POINTS = OVERNIGHT_COUNT + MORNING_COUNT + PREGAME_COUNT  # 53

# Fixture role/model mapping per run_context (MOCK, non-approved; catalog-backed).
_CONTEXT_MODEL = {
    "Overnight": "qwen.qwen3-32b-v1:0",
    "Morning": "deepseek.v3.2",
    "PreGame": "moonshotai.kimi-k2.5",
}
_CONTEXT_LAYER = {
    "Overnight": "framing",
    "Morning": "analyst",
    "PreGame": "analyst",
}
_CONTEXT_COMPONENT = {
    "Overnight": "framing",
    "Morning": "analyst_s1",
    "PreGame": "analyst_s3",
}
# analyst slots for the 26-count runs (fixture; not an approval of any roster)
_SLOTS = ["s01", "s02", "s03", "s04", "s05"]


def build_call_points() -> list[ProviderCall]:
    points: list[ProviderCall] = []
    call_idx = 0
    for ctx, count in (("Overnight", OVERNIGHT_COUNT), ("Morning", MORNING_COUNT), ("PreGame", PREGAME_COUNT)):
        for n in range(1, count + 1):
            call_idx += 1
            slot = None
            if ctx != "Overnight":
                slot = _SLOTS[n % len(_SLOTS)]
            points.append(
                ProviderCall(
                    model_id=_CONTEXT_MODEL[ctx],
                    component=_CONTEXT_COMPONENT[ctx],
                    run_id="MOCKRUN-1/26/26",
                    layer=_CONTEXT_LAYER[ctx],
                    source="mock.bedrock-mantle.local",
                    analyst_slot=slot,
                    prompt=f"{ctx} call point {call_idx}",
                    max_attempts=3,
                    request_meta={"run_context": ctx, "call_point": call_idx, "ordinal_in_context": n},
                )
            )
    return points


def run_orchestration(harness: Path) -> dict:
    # disposable harness state under wave1/.harness/
    ledger = Ledger(harness / "ledger.jsonl")
    ledger._reset_file()
    events = Emitter(harness / "events.jsonl")
    # zero backoff for the mock run (fast, deterministic); no live spend
    provider = MockProvider(ledger, on_emit=events.emit, backoff_seconds=(0.0, 0.0))

    # program failures to demonstrate extra ledger rows (representative, not exhaustive)
    #  - call point 2 (Morning #1): transient-fails once, then succeeds -> +1 retry row
    #  - call point 28 (PreGame #1): terminal-fails -> its own failed row
    provider.program_transient(call_point=2, times=1)
    provider.program_terminal(call_point=28)

    call_points = build_call_points()
    results = []
    for cp in call_points:
        res = provider.execute(cp)
        results.append({"call_point": cp.request_meta["call_point"], "run_context": cp.request_meta["run_context"], "status": res["status"], "model_id": cp.model_id})

    return {
        "ledger_path": str(ledger.path),
        "ledger_row_count": ledger.count(),
        "events_path": str(events.path),
        "events_count": len(events.all()),
        "call_points_total": len(call_points),
        "results": results,
    }


def demo_no_retrofit(harness: Path) -> dict:
    """No-retrofit proof: remove the calling layer. A bare ProviderCall driven through the
    provider abstraction STILL meters — because the meter is in the provider, not the caller."""
    ledger = Ledger(harness / "no_retrofit_ledger.jsonl")
    ledger._reset_file()
    events = Emitter(harness / "no_retrofit_events.jsonl")
    provider = MockProvider(ledger, on_emit=events.emit, backoff_seconds=(0.0, 0.0))
    cp = ProviderCall(
        model_id="deepseek.v3.2",
        component="analyst_s1",
        run_id="NORETROFIT-1",
        layer="analyst",
        source="mock.bedrock-mantle.local",
        prompt="no-caller-orchestration direct provider call",
        max_attempts=1,
        request_meta={"run_context": "Morning", "call_point": 999, "ordinal_in_context": 1},
    )
    # no orchestration loop, no caller-side ledger write — just the provider execution point
    res = provider.execute(cp)
    rows = ledger.read_all()
    return {
        "status": res["status"],
        "ledger_row_count_after_direct_execute": len(rows),
        "rows_metered_without_caller": [r["outcome"] for r in rows],
        "proves_meter_in_provider": len(rows) >= 1,
    }


def main() -> int:
    harness = Path(__file__).resolve().parents[1] / ".harness"
    harness.mkdir(parents=True, exist_ok=True)
    run = run_orchestration(harness)
    noretrofit = demo_no_retrofit(harness)

    print("=== WAVE 1 MOCK ORCHESTRATION (1/26/26) ===")
    print(f"call points assembled : {run['call_points_total']}  (1 + 26 + 26)")
    print(f"ledger rows           : {run['ledger_row_count']}")
    print(f"events emitted        : {run['events_count']}")
    print("\nper-call result summary (call_point: run_context: status)")
    for r in run["results"]:
        print(f"  {r['call_point']}: {r['run_context']}: {r['status']}  ({r['model_id']})")
    print("\n=== NO-RETROFIT PROOF (meter in provider, no calling layer) ===")
    print(json.dumps(noretrofit, indent=2))
    print("\nledger + events persisted under: ", run["ledger_path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
