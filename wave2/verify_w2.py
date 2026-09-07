"""Wave 2 acceptance verification — asserts brief §5 W2-C1..C10 and prints PASS/FAIL per
criterion. Replayable, offline, no live provider traffic. Adjudication belongs to Luce;
this build returns results and does not self-pass.

Supplemental scaffold demonstrations (X1 contamination, X2 fallback) are reported
separately: they exercise in-scope surfaces not named by a lettered criterion.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ec8wave2 import demo as demo_mod

RESULTS: dict[str, bool] = {}
NOTES: dict[str, str] = {}


def rec(cid: str, ok: bool, note: str = ""):
    RESULTS[cid] = bool(ok)
    NOTES[cid] = note
    print(f"{cid}: {'PASS' if ok else 'FAIL'}  {note}")


def run_all() -> dict[str, bool]:
    harness = Path(__file__).resolve().parent / ".harness"
    harness.mkdir(parents=True, exist_ok=True)

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
    }
    supplemental = {
        "W2-X1": demo_mod.demo_x1_contamination,
        "W2-X2": demo_mod.demo_x2_fallback,
    }

    detail: dict[str, dict] = {}
    for cid, fn in mapping.items():
        try:
            result = fn(harness)
        except Exception as exc:  # demo raised unexpectedly -> FAIL surfaced, never silent
            result = {"ok": False, "raised": f"{type(exc).__name__}: {exc}"}
        ok = bool(result.get("ok"))
        rec(cid, ok)
        detail[cid] = {k: v for k, v in result.items() if k != "ok"}

    for cid, fn in supplemental.items():
        try:
            result = fn(harness)
        except Exception as exc:
            result = {"ok": False, "raised": f"{type(exc).__name__}: {exc}"}
        ok = bool(result.get("ok"))
        rec(cid, ok)
        detail[cid] = {k: v for k, v in result.items() if k != "ok"}

    log = {
        "criteria": RESULTS,
        "notes": NOTES,
        "supplemental": {k: RESULTS[k] for k in supplemental},
        "detail": detail,
    }
    (harness / "verify_w2_detail.json").write_text(json.dumps(log, indent=2), encoding="utf-8")
    return RESULTS


if __name__ == "__main__":
    res = run_all()
    acceptance = {k: v for k, v in res.items() if k.startswith("W2-C")}
    n_pass = sum(acceptance.values())
    all_pass = n_pass == len(acceptance) == 10
    print(f"\nW2 RESULT: {'ALL PASS (10/10)' if all_pass else f'{n_pass}/10 PASS'}")
    print("SUMMARY: " + ", ".join(f"{k}={v}" for k, v in res.items()))
    sys.exit(0 if all_pass else 1)
