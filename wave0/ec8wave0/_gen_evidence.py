"""Generate raw Wave 0 runtime evidence data files (no secret values) used to assemble the
§8 evidence package. Writes only under .harness/ev/ — never to production store.
"""
from __future__ import annotations

import json
import os
import sys
import hashlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ec8wave0 import store as S
from ec8wave0 import serializer as ser
from ec8wave0 import secret_fence as SF

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / ".harness"
EV = HARNESS / "ev"
EV.mkdir(parents=True, exist_ok=True)

FIXTURE_SECRET_ENV = "EC8_W0_FIXTURE_SECRET"
FIXTURE_SECRET = "w0-audition-secret-not-for-store"

A = {
    "entity": "player:test-001", "attribute": "batting_average",
    "snapshot_time": "2026-09-06T00:00:00Z", "acquired_at": "2026-09-06T01:00:00Z",
    "source": "fixture.source.w0", "reliability_tier": "Medium", "run_type": "Morning",
    "expires_at": "2026-09-07T00:00:00Z", "content": {"ba": 0.300},
}
B = dict(A, snapshot_time="2026-09-06T12:00:00Z", content={"ba": 0.310})


def reset():
    st = S.EvidenceStore(HARNESS / "ev_store")
    for p in (HARNESS / "ev_store").rglob("*"):
        if p.is_file():
            p.unlink()
    return st


st = reset()
ra = st.write(A)
shaA = ra["content_sha256"]
rb = st.write(B)
items = st.list_items()
shaB = [it["content_sha256"] for it in items if it["snapshot_time"] == "2026-09-06T12:00:00Z"][0]

# --- HASHES.md data ---
hash_rows = {
    "fixture_A_content_sha256": shaA,
    "fixture_B_content_sha256": shaB,
    "fixture_A_recomputed": ser.sha256_hex(A),
    "fixture_B_recomputed": ser.sha256_hex(B),
}
(EV / "hashes.json").write_text(json.dumps(hash_rows, indent=2), encoding="utf-8")

# --- PROVENANCE.md data (round-trip dumps, no secrets) ---
dumpA = st.read(shaA)["item"]
dumpB = st.read(shaB)["item"]
(EV / "provenance_A.json").write_text(json.dumps(dumpA, indent=2, sort_keys=True), encoding="utf-8")
(EV / "provenance_B.json").write_text(json.dumps(dumpB, indent=2, sort_keys=True), encoding="utf-8")

# --- BACKUP_RESTORE.md data ---
bres = st.backup()
backup_id = bres["backup_id"]
manifest_hash = bres["manifest_hash"]
manifest_raw = (st.backups_dir / backup_id / "MANIFEST.json").read_text(encoding="utf-8")
backup_files = sorted(p.name for p in (st.backups_dir / backup_id / "objects").iterdir())
(EV / "backup.json").write_text(json.dumps({
    "status": bres["status"], "backup_id": backup_id, "manifest_hash": manifest_hash,
    "backup_object_files": backup_files,
}, indent=2), encoding="utf-8")
(EV / "backup_manifest.json").write_text(manifest_raw, encoding="utf-8")

# wipe disposable objects, restore, verify
before_restore_count = st.object_count()
for p in st._object_files():
    p.unlink()
rrest = st.restore(backup_id)
verify_after = {"A": st.verify(shaA)["status"], "B": st.verify(shaB)["status"]}
(EV / "restore.json").write_text(json.dumps({
    "emptied_before_restore": before_restore_count,
    "restore_result": rrest,
    "verify_after_restore": verify_after,
    "final_item_count": st.object_count(),
}, indent=2), encoding="utf-8")

# --- SECRET_ISOLATION.md data (counts only) ---
secret_val = os.environ.get(FIXTURE_SECRET_ENV, FIXTURE_SECRET)
sec = secret_val.encode()
sc_store = SF.scan_path(st.objects_dir, sec)
sc_backup = SF.scan_path(st.backups_dir, sec)
live_present = "no"
live_hits = 0
live_tok = os.environ.get("AWS_BEARER_TOKEN_BEDROCK")
if live_tok:
    live_present = "yes"
    live_hits = SF.scan_path(st.objects_dir, live_tok.encode()) + SF.scan_path(st.backups_dir, live_tok.encode())
(EV / "secret_scan.json").write_text(json.dumps({
    "fixture_hits_store": sc_store, "fixture_hits_backup": sc_backup,
    "fixture_hits_total": sc_store + sc_backup,
    "live_token_hits": live_hits, "live_token_present": live_present,
    "note": "counts only; secret values never recorded",
}, indent=2), encoding="utf-8")

print(json.dumps({"ok": True, "shaA": shaA, "shaB": shaB, "backup_id": backup_id, "manifest_hash": manifest_hash}, indent=2))
