"""Produce clean, single-run Wave 1 runtime evidence artifacts under wave1/.harness/ev/
for the §8-equivalent package. One fresh orchestration + no-retrofit demo + catalog trace.
No secret values are ever written.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ec8wave1.ledger import Ledger
from ec8wave1.provider import MockProvider, ProviderCall
from ec8wave1.catalog import MockCatalog
from ec8wave1.observability import Emitter
from ec8wave1 import mock_run as mr

EV = Path(__file__).resolve().parents[1] / ".harness" / "ev"
EV.mkdir(parents=True, exist_ok=True)

# clean single orchestration run
run = mr.run_orchestration(EV)  # ledger + events under .harness/ev
ledger = Ledger(run["ledger_path"])
# read emitted events back from the persisted append-only file (not an empty new Emitter)
def _load_events(path: Path) -> list:
    out = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out
events_list = _load_events(Path(run["events_path"]))

# catalog trace
cat = MockCatalog()
catalog_trace = {"behavior": "local GET /v1/models equivalent", "live_gateway_contacted": False, "entries": cat.list_models()}
(EV / "catalog_trace.json").write_text(json.dumps(catalog_trace, indent=2), encoding="utf-8")

# ledger + events copies
ledger_rows = ledger.read_all()
(EV / "ledger_rows.json").write_text(json.dumps(ledger_rows, indent=2), encoding="utf-8")
(EV / "events.json").write_text(json.dumps(events_list, indent=2), encoding="utf-8")

# no-retrofit demo
nr = mr.demo_no_retrofit(EV)
(EV / "no_retrofit.json").write_text(json.dumps(nr, indent=2), encoding="utf-8")

# outcome histogram + per-run summary
hist: dict[str, int] = {}
for r in ledger_rows:
    hist[r["outcome"]] = hist.get(r["outcome"], 0) + 1
ctx_hist: dict[str, int] = {}
for r in ledger_rows:
    ctx = r.get("run_context", "?")
    ctx_hist[ctx] = ctx_hist.get(ctx, 0) + 1
(EV / "summary.json").write_text(json.dumps({
    "call_points_total": run["call_points_total"],
    "topology": {"Overnight": 1, "Morning": 26, "PreGame": 26},
    "ledger_row_count": len(ledger_rows),
    "outcome_histogram": hist,
    "context_histogram": ctx_hist,
    "events_count": len(events_list),
    "zero_live_provider_traffic": True,
}, indent=2), encoding="utf-8")

print(json.dumps({"ok": True, "ledger_rows": len(ledger_rows), "events": len(events_list), "hist": hist, "ctx": ctx_hist}))
