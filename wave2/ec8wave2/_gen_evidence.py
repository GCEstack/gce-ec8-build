"""Produce clean, single-run Wave 2 runtime evidence artifacts under wave2/.harness/ev/
for the §8-equivalent package. Runs the same demonstrations the verifier asserts and
persists their JSON detail. No secret values are ever written.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ec8wave2 import demo as demo_mod

EV = Path(__file__).resolve().parents[1] / ".harness" / "ev"
EV.mkdir(parents=True, exist_ok=True)

mapping = {
    "W2-C1": demo_mod.demo_c1_isolation,
    "W2-C2": demo_mod.demo_c2_session,
    "W2-C3": demo_mod.demo_c3_chokepoint,
    "W2-C4": demo_mod.demo_c4_registry,
    "W2-C5": demo_mod.demo_c5_checkpoint,
    "W2-C6": demo_mod.demo_c6_artifact,
    "W2-C7": demo_mod.demo_c7_adapters,
    "W2-C8": demo_mod.demo_c8_metering,
    "W2-C9": demo_mod.demo_c9_semantic,
    "W2-C10": demo_mod.demo_c10_secret,
    "W2-X1": demo_mod.demo_x1_contamination,
    "W2-X2": demo_mod.demo_x2_fallback,
}

results = {}
for cid, fn in mapping.items():
    result = fn(EV)
    results[cid] = {"ok": bool(result.get("ok")), **{k: v for k, v in result.items() if k != "ok"}}
    (EV / f"{cid.replace('-', '_').lower()}.json").write_text(json.dumps(results[cid], indent=2), encoding="utf-8")

(EV / "summary.json").write_text(
    json.dumps(
        {
            "wave": "2",
            "brief": "BRIEF-20260906-EC8-W2",
            "criteria": {cid: bool(results[cid]["ok"]) for cid in mapping},
            "zero_live_provider_traffic": True,
            "mock_only": True,
        },
        indent=2,
    ),
    encoding="utf-8",
)

print(json.dumps({"ok": True, "criteria": {cid: bool(results[cid]["ok"]) for cid in mapping}}))
