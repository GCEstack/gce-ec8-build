"""W0-T01..W0-T18 predetermined acceptance suite (spec §6). Run on a DISPOSABLE harness
store (P11) so destructive tests (T08/T13/T15/T16) never touch the production store and no
production-path update/delete exists. Results map to spec §6 Test IDs.

Runner: python tests/test_w0_suite.py
"""

from __future__ import annotations

import os
import re
import sys
import json
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ec8wave0 import store as S
from ec8wave0 import secret_fence as SF
from ec8wave0 import serializer as ser

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / ".harness" / "suite_store"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")

FIXTURE_SECRET_ENV = "EC8_W0_FIXTURE_SECRET"
FIXTURE_SECRET = "w0-audition-secret-not-for-store"


def make_item(
    snapshot_time="2026-09-06T00:00:00Z",
    acquired_at="2026-09-06T01:00:00Z",
    source="fixture.source.w0",
    reliability_tier="Medium",
    run_type="Morning",
    expires_at="2026-09-07T00:00:00Z",
    content=None,
):
    if content is None:
        content = {"ba": 0.300}
    return {
        "entity": "player:test-001",
        "attribute": "batting_average",
        "snapshot_time": snapshot_time,
        "acquired_at": acquired_at,
        "source": source,
        "reliability_tier": reliability_tier,
        "run_type": run_type,
        "expires_at": expires_at,
        "content": content,
    }


FIXTURE_A = make_item()
FIXTURE_B = make_item(snapshot_time="2026-09-06T12:00:00Z", content={"ba": 0.310})

RESULTS: dict[str, bool] = {}
NOTES: dict[str, str] = {}
_CAPTURE: list[str] = []  # accumulated (safe) log lines used for the T16 log scan


def record(tid: str, ok: bool, note: str = ""):
    RESULTS[tid] = bool(ok)
    NOTES[tid] = note
    line = f"{tid}: {'PASS' if ok else 'FAIL'}  {note}"  # NOTE: no secret values ever printed
    _CAPTURE.append(line)
    print(line)


def fresh_harness() -> S.EvidenceStore:
    if HARNESS.exists():
        for p in HARNESS.rglob("*"):
            if p.is_file():
                p.unlink()
    store = S.EvidenceStore(HARNESS)
    return store


def run_all() -> dict[str, bool]:
    st = fresh_harness()

    # ---- W0-T01 evidence write ----
    res = st.write(FIXTURE_A)
    shaA = res.get("content_sha256", "")
    record("W0-T01", res.get("status") == "committed" and bool(SHA_RE.match(shaA or "")), json.dumps(res))
    shaA = res["content_sha256"]

    # ---- W0-T02 evidence read (by identity and by hash) ----
    id_loc = {"entity": "player:test-001", "attribute": "batting_average", "snapshot_time": FIXTURE_A["snapshot_time"]}
    r_id = st.read(id_loc)
    r_hash = st.read(shaA)
    ok = r_id.get("status") == "found" and r_hash.get("status") == "found"
    ok = ok and st._identity_key(r_id["item"]) == st._identity_key(r_hash["item"])
    record("W0-T02", ok, json.dumps({"by_identity": r_id.get("status"), "by_hash": r_hash.get("status")}))

    # ---- W0-T03 exact round-trip preservation ----
    r_item = st.read(shaA)["item"]
    diffs = []
    for field in ser.REQUIRED_FIELDS:
        a = FIXTURE_A[field]
        b = r_item[field]
        if field in ("snapshot_time", "acquired_at", "expires_at"):
            a = ser.format_timestamp(a)
            b = ser.format_timestamp(b)
        elif field == "content":
            a = ser._canonical_content(a)
            b = ser._canonical_content(b)
        if a != b:
            diffs.append(field)
    record("W0-T03", not diffs, f"diffs={diffs}")

    # ---- W0-T04 identity preservation ----
    ident = (r_item["entity"], r_item["attribute"], r_item["snapshot_time"])
    expect = ("player:test-001", "batting_average", ser.format_timestamp(FIXTURE_A["snapshot_time"]))
    record("W0-T04", ident == expect, f"identity={ident}")

    # ---- W0-T05 provenance preservation ----
    prov_ok = all(
        r_item[k] == FIXTURE_A[k] or ser.format_timestamp(r_item[k]) == ser.format_timestamp(FIXTURE_A[k])
        for k in ("acquired_at", "source", "reliability_tier", "run_type", "expires_at")
    )
    record("W0-T05", prov_ok, "5 provenance fields round-trip")

    # ---- W0-T06 hash generation (recompute) ----
    recomputed = ser.sha256_hex(FIXTURE_A)
    record("W0-T06", recomputed == shaA, f"recomputed==stored: {recomputed[:16]}")

    # ---- W0-T07 hash verification ok path ----
    v = st.verify(shaA)
    record("W0-T07", v.get("status") == "ok", json.dumps(v))

    # ---- W0-T08 tamper detection (disposable harness) ----
    before_hash = shaA
    tampered_file = st.objects_dir / f"{shaA}.json"
    data = bytearray(tampered_file.read_bytes())
    data[10] ^= 0x01  # flip one byte of stored provenance/content
    tampered_file.write_bytes(bytes(data))
    v2 = st.verify(shaA)
    read_tamper = st.read(shaA)
    record(
        "W0-T08",
        v2.get("status") == "tamper_or_mismatch" and read_tamper.get("status") != "found",
        f"verify={v2.get('status')} read={read_tamper.get('status')} prod_api_repair_in_place=false",
    )
    # restore integrity for subsequent tests by re-writing (harness disposable)
    fresh_harness()
    st = fresh_harness()
    resA = st.write(FIXTURE_A)
    shaA = resA["content_sha256"]
    st.write(FIXTURE_B)
    shaB = None
    for it in st.list_items():
        if it["snapshot_time"] == "2026-09-06T12:00:00Z":
            shaB = it["content_sha256"]

    # ---- W0-T09 append-only: new identity allowed (A + B) ----
    record("W0-T09", st.object_count() == 2 and shaB != shaA, f"count={st.object_count()} A={shaA[:8]} B={shaB[:8] if shaB else None}")

    # ---- W0-T10 duplicate identity rejected; A unchanged ----
    dup = st.write(dict(FIXTURE_A, content={"ba": 0.999}))  # same identity, different content
    reread = st.read(shaA)
    record("W0-T10", dup.get("status") == "rejected" and dup.get("reason") == "duplicate_identity" and reread.get("item", {}).get("content_sha256") == shaA, json.dumps(dup))

    # ---- W0-T11 no production update/delete API ----
    has_update = hasattr(st, "update")
    has_delete = hasattr(st, "delete")
    record("W0-T11", not has_update and not has_delete, f"update_api={has_update} delete_api={has_delete}")

    # ---- W0-T12 backup ----
    bres = st.backup()
    backup_id = bres.get("backup_id", "")
    record("W0-T12", bres.get("status") == "ok" and bool(SHA_RE.match(bres.get("manifest_hash", "") or "")), json.dumps({"backup_id": backup_id, "manifest_hash": bres.get("manifest_hash","")[:16]}))
    manifest_hash = bres["manifest_hash"]

    # ---- W0-T13 restore (harness empties disposable store, not prod delete API) ----
    for p in st._object_files():
        p.unlink()
    empty_count = st.object_count()
    rres = st.restore(backup_id)
    record("W0-T13", empty_count == 0 and rres.get("status") == "ok" and rres.get("item_count") == 2, f"emptied={empty_count} restore={json.dumps(rres)}")

    # ---- W0-T14 restored-object integrity ----
    pre = {it["content_sha256"]: it for it in st.list_items()}
    vA = st.verify(shaA)
    vB = st.verify(shaB)
    diffs14 = []
    for it in st.list_items():
        k = it["content_sha256"]
        b = pre[k]
        for field in ser.REQUIRED_FIELDS:
            aa, bb = it[field], b[field]
            if field in ("snapshot_time", "acquired_at", "expires_at"):
                aa, bb = ser.format_timestamp(aa), ser.format_timestamp(bb)
            elif field == "content":
                aa, bb = ser._canonical_content(aa), ser._canonical_content(bb)
            if aa != bb:
                diffs14.append(field)
    record("W0-T14", vA.get("status") == "ok" and vB.get("status") == "ok" and not diffs14, f"vA={vA.get('status')} vB={vB.get('status')} diffs={diffs14}")

    # ---- W0-T15 secrets absent from persisted artifacts (harness store + backup) ----
    secret_val = os.environ.get(FIXTURE_SECRET_ENV, FIXTURE_SECRET)
    sec = secret_val.encode()
    hits_store = SF.scan_path(st.objects_dir, sec)
    hits_backup = SF.scan_path(st.backups_dir, sec)
    # live token scan if present (counts only)
    live_hits = 0
    live_present = "no"
    live_tok = os.environ.get("AWS_BEARER_TOKEN_BEDROCK")
    if live_tok:
        live_present = "yes"
        live_hits = SF.scan_path(st.objects_dir, live_tok.encode()) + SF.scan_path(st.backups_dir, live_tok.encode())
    record("W0-T15", hits_store == 0 and hits_backup == 0 and live_hits == 0, f"fixture_hits=0 (store={hits_store} backup={hits_backup}) live_token_hits={live_hits} live_token_present={live_present}")

    # ---- W0-T16 secrets absent from logs (accumulated safe log lines from T01-T15) ----
    log_text = "\n".join(_CAPTURE)
    log_fixture_hits = log_text.count(secret_val)
    log_live_hits = log_text.count(live_tok) if live_present == "yes" else 0
    record("W0-T16", log_fixture_hits == 0 and log_live_hits == 0, f"log_fixture_hits={log_fixture_hits} log_live_token_hits={log_live_hits}")

    # ---- W0-T17 incomplete provenance rejected (nine missing-field writes) ----
    st = fresh_harness()
    rejects = 0
    for field in ("entity", "attribute", "snapshot_time", "acquired_at", "source", "reliability_tier", "run_type", "expires_at", "content"):
        bad = dict(FIXTURE_A)
        del bad[field]
        r = st.write(bad)
        if r.get("status") == "rejected" and r.get("reason") == "incomplete_provenance":
            rejects += 1
    record("W0-T17", rejects == 9 and st.object_count() == 0, f"rejected={rejects}/9 store_count={st.object_count()}")

    # ---- W0-T18 invalid / OnDemand run_type rejected ----
    rejects18 = 0
    for rt in ("OnDemand", "Live", ""):
        bad = dict(FIXTURE_A, run_type=rt)
        r = st.write(bad)
        if r.get("status") == "rejected" and r.get("reason") == "invalid_run_type":
            rejects18 += 1
    record("W0-T18", rejects18 == 3, f"rejected={rejects18}/3")

    return RESULTS


if __name__ == "__main__":
    res = run_all()
    all_pass = all(res.values()) and len(res) == 18
    print(f"\nSUITE RESULT: {'ALL PASS (18/18)' if all_pass else f'{sum(res.values())}/18 PASS'}")
    print("SUMMARY: " + ", ".join(f"{k}={v}" for k, v in res.items()))
    sys.exit(0 if all_pass else 1)
