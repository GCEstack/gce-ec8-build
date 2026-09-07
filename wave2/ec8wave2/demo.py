"""Wave 2 harness demonstrations (one function per acceptance criterion).

Each demo writes disposable state under the caller-supplied harness root and returns a
plain-dict result that verify_w2.py asserts on and _gen_evidence.py persists. Nothing
here touches the network; all provider work flows through W1 MockProvider (execution-point
metering, no-retrofit). Adjudication of these results belongs to Luce, not to this build.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from . import WAVE2_ROOT
from . import _stubs
from .adapters import NormalizerAdapter, ValidationAdapter
from .artifact import (
    SECTIONS,
    build_artifact_id,
    resolve_terminal,
    reseal_after_change,
    seal,
    structural_validate,
    verify_seal,
    version_change_kind,
)
from .assembler import Assembler
from .checkpoint import EXCLUSION_REASON_CRASH_LIMIT, CheckpointStore
from .contamination import CanaryProgram, Fingerprinter, PairwiseSampler
from .fallback import FallbackProvider, registry_entry_eligible
from .iso import isolation_proof
from .registry import EX2Preflight, Registry, RegistryPinner
from .session import SessionRegistry, verify_session_continuity

PROD_MODULES = (
    "__init__.py",
    "_stubs.py",
    "iso.py",
    "session.py",
    "assembler.py",
    "registry.py",
    "checkpoint.py",
    "artifact.py",
    "adapters.py",
    "contamination.py",
    "fallback.py",
)


def _conforming_artifact(slate_id: str = "MLB-2026-0906", run_type: str = "PreGame", ts: str = "20260906T190000Z") -> dict:
    return {
        "header": {
            "artifact_id": build_artifact_id(slate_id, run_type, ts),
            "artifact_schema_version": "1.0",
            "methodology_version": "0.3.1",
            "run_id": "R-demo",
            "generated_at": ts,
        },
        "S1": {"slate_id": slate_id, "matchups": [], "run_type": run_type, "configured_parameters": {"N": 5}},
        "S2": {"framing_instance_ref": "fixture", "schema_version": "0.3-MLB"},
        "S3": {
            "configured_n": 5,
            "ran_n": 5,
            "included_n": 5,
            "excluded_n": 0,
            "exclusions": [],
            "retry_count": 0,
            "crash_restart_count": 0,
        },
        "S4": [],
        "S5": [],
        "S6": [],
        "S7": {},
        "S8": {},
        "S9": {"canary_scans": [], "fingerprints": [], "gate_outcomes": [], "continuity_verification": "ok"},
    }


def demo_c1_isolation(harness: Path) -> dict:
    result = isolation_proof(harness / "c1", ("A", "B"), "EC8_PARENT_SECRET_ISOLATION")
    ok = (
        result["run_ids_unique"]
        and result["canaries_unique"]
        and result["all_returncodes_ok"]
        and not result["child_env_leaks_of_parent_secret"]
        and not result["identity_mismatch"]
        and all(result["marker_parent_is_own_root"].values())
        and not result["stderr"]
    )
    return {"ok": ok, "detail": result}


def demo_c2_session(harness: Path) -> dict:
    reg = SessionRegistry()
    recs = []
    for run_id, stage in (("R1", "Stage1"), ("R1", "Stage3"), ("R2", "Stage1"), ("R2", "Stage3")):
        sid = reg.open(run_id, "s01", stage)
        recs.append(reg.records()[-1])
        if run_id == "R1" and stage == "Stage1":
            r1_s1 = sid
        if run_id == "R2" and stage == "Stage1":
            r2_s1 = sid
    violations_clean = verify_session_continuity(recs)
    import copy
    bad = copy.deepcopy(recs)
    bad[0].session_id = r2_s1
    violations_bad = verify_session_continuity(bad)
    return {
        "ok": not violations_clean and any(v["kind"] == "inter_run_reuse" for v in violations_bad),
        "r1_stage1_stage3_same": None,
        "violations_clean": violations_clean,
        "violations_when_reused": violations_bad,
        "intra_run_records": [{"run": r.run_id, "slot": r.slot, "stage": r.stage, "session": r.session_id} for r in recs],
    }


def demo_c3_chokepoint(harness: Path) -> dict:
    from .demo_store import MockEvidenceStore

    store = MockEvidenceStore(harness / "c3_store.jsonl")
    store.add_item("entity.e", "attr.pts", "2026-09-06", {"value": 21.5})
    assembler = Assembler(store=store)
    pkg_a = assembler.assemble_package("MLB-X", "R1", "persona:A", ["req.1"], {"req.1": "filled"})
    pkg_b = assembler.assemble_package("MLB-X", "R1", "persona:D", ["req.2"], {"req.2": "unfilled"})
    single_path = assembler.assembly_calls == 2 and pkg_a.assembled_by == "IF2_CHOKEPOINT" and pkg_b.assembled_by == "IF2_CHOKEPOINT"
    store_reads = len(assembler._read_trace) == 2
    assembler.track_bypass("attempted direct envelope construction")
    bypass_flag = assembler.bypass_detected == 1
    return {"ok": single_path and store_reads and bypass_flag, "assembly_calls": assembler.assembly_calls, "bypass_detected": assembler.bypass_detected}


def demo_c4_registry(harness: Path) -> dict:
    pr = Registry(harness / "c4_pr2.jsonl", "pr2", ("family_id", "provider_org", "model_id", "version_id", "capability_classes", "status"))
    rg = Registry(harness / "c4_rg1.jsonl", "rg1", ("entity_type", "league", "season", "entity_id", "canonical_name", "aliases", "validity_window", "source_of_truth", "version"))
    fixture = [
        {"family_id": "qwen", "provider_org": "alibaba", "model_id": "qwen.qwen3-235b-a22b-2507-v1:0", "version_id": "v1", "capability_classes": ["analyst"], "status": "fixture"},
        {"family_id": "deepseek", "provider_org": "deepseek", "model_id": "deepseek.v3.2", "version_id": "v1", "capability_classes": ["analyst", "l2"], "status": "fixture"},
        {"family_id": "kimi", "provider_org": "moonshot", "model_id": "moonshotai.kimi-k2.5", "version_id": "v1", "capability_classes": ["analyst"], "status": "fixture"},
        {"family_id": "glm", "provider_org": "zai", "model_id": "zai.glm-5", "version_id": "v1", "capability_classes": ["analyst"], "status": "fixture"},
        {"family_id": "mistral", "provider_org": "mistral", "model_id": "mistral.mistral-large-3-675b-instruct", "version_id": "v1", "capability_classes": ["l3"], "status": "fixture"},
        {"family_id": "claude", "provider_org": "anthropic", "model_id": "anthropic.claude-haiku-4-5-20251001-v1:0", "version_id": "v1", "capability_classes": ["l3_fallback"], "status": "fixture"},
    ]
    for e in fixture:
        pr.register(e)
    rg.register({"entity_type": "team", "league": "MLB", "season": "2026", "entity_id": "team.TEX", "canonical_name": "Texas Rangers", "aliases": [], "validity_window": "2026-03-01..2026-11-01", "source_of_truth": "governance-designated", "version": "1"})

    preflight_ok = EX2Preflight(pr).run(
        analyst_ids=["qwen.qwen3-235b-a22b-2507-v1:0", "deepseek.v3.2", "moonshotai.kimi-k2.5", "zai.glm-5"],
        l2_pairs=[("deepseek.v3.2", "qwen.qwen3-235b-a22b-2507-v1:0"), ("qwen.qwen3-235b-a22b-2507-v1:0", "deepseek.v3.2"), ("deepseek.v3.2", "moonshotai.kimi-k2.5")],
        l3_ids=["mistral.mistral-large-3-675b-instruct"],
        ledger_row_count_at_check=0,
    )
    preflight_bad = EX2Preflight(pr).run(
        analyst_ids=["qwen.qwen3-235b-a22b-2507-v1:0"],
        l2_pairs=[],
        l3_ids=["deepseek.v3.2"],
        ledger_row_count_at_check=0,
    )
    pinner = RegistryPinner()
    pinner.pin("rg1", rg.rows())
    return {
        "ok": preflight_ok.ok and preflight_ok.checked_before_spend and not preflight_bad.ok,
        "pr2_rows": len(pr.rows()),
        "rg1_rows": len(rg.rows()),
        "preflight_ok": preflight_ok.violations,
        "preflight_bad": preflight_bad.violations,
        "pin": pinner.pins["rg1"],
    }


def demo_c5_checkpoint(harness: Path) -> dict:
    ck = CheckpointStore(harness / "c5_ck.jsonl", "R-CK")
    counters: dict[str, dict] = {"s01": {"validation_retries": 0, "crash_restarts": 0, "excluded": None}}
    ck.checkpoint_gate("G0", {"run_id": "R-CK"}, ["g0.out"], counters, 1)
    ck.record_validation_retry("s01", counters)
    ck.checkpoint_gate("G1", {"run_id": "R-CK"}, ["g0.out", "g1.out"], counters, 1)
    ck.record_crash_restart("s01", counters)
    ck.checkpoint_gate("G2", {"run_id": "R-CK"}, ["g0.out", "g1.out", "g2.out"], counters, 1)
    ck.record_crash_restart("s01", counters)

    resumed = ck.resume_state()["analyst_counters"]["s01"]
    resumed_retries = resumed["validation_retries"]
    resumed_restarts = resumed["crash_restarts"]
    snap_before = {"validation_retries": 1, "crash_restarts": 1}

    ck.record_crash_restart("s01", counters)
    ck.record_crash_restart("s01", counters)
    excluded = counters["s01"]["excluded"] == EXCLUSION_REASON_CRASH_LIMIT

    ck_isolated = CheckpointStore(harness / "c5_tbound.jsonl", "R-TB")
    unconfigured = ck_isolated.check_t_bound(now=100.0, window_close=200.0)["status"] == "unconfigured"
    ck_isolated.authorize_clock("TALON-CLOCK")
    exhausted = ck_isolated.check_t_bound(now=300.0, window_close=200.0)["status"] == "exhausted"
    inside = ck_isolated.check_t_bound(now=150.0, window_close=200.0)["status"] == "ok"
    return {
        "ok": resumed_retries == snap_before["validation_retries"] and resumed_restarts == snap_before["crash_restarts"]
        and excluded and unconfigured and exhausted and inside,
        "counters_at_last_passed_gate": snap_before,
        "resumed_counters": {"validation_retries": resumed_retries, "crash_restarts": resumed_restarts},
        "counters_survived_resume": resumed_retries == snap_before["validation_retries"] and resumed_restarts == snap_before["crash_restarts"],
        "after_crash_calls": counters["s01"],
        "exclusion_after_gt2_crashes": excluded,
        "t_bound": {"unconfigured": unconfigured, "exhausted": exhausted, "inside": inside},
    }


def demo_c6_artifact(harness: Path) -> dict:
    import copy

    good = _conforming_artifact()
    good_v = structural_validate(good)
    bad = _conforming_artifact()
    del bad["S5"]
    bad["header"].pop("artifact_schema_version", None)
    bad_v = structural_validate(bad)

    minor_ok = version_change_kind("1.0", "1.1", new_enum_introduced=False)
    enum_major_required = version_change_kind("1.0", "1.1", new_enum_introduced=True)

    morning = _conforming_artifact(run_type="Morning", ts="20260906T110000Z")
    pregame = _conforming_artifact(run_type="PreGame", ts="20260906T190000Z")
    terminal_ok = resolve_terminal("MLB-X", pregame=pregame, morning=morning, pregame_failed=False)
    terminal_fail = resolve_terminal("MLB-X", pregame=pregame, morning=morning, pregame_failed=True)

    sealed = seal(good)
    tamper = copy.deepcopy(good)
    tamper["S1"]["slate_id"] = "MUTATED"
    seal_verified = verify_seal(good, sealed["sha256"])
    tamper_detected = not verify_seal(tamper, sealed["sha256"])
    resealed = reseal_after_change(tamper, "post-seal correction")
    return {
        "ok": not good_v and len(bad_v) >= 2 and minor_ok["kind"] == "ok_additive" and enum_major_required["kind"] == "not_allowed"
        and terminal_ok["status"] == "complete" and terminal_ok["terminal_artifact_id"] is not None
        and terminal_fail["status"] == "failed" and terminal_fail["terminal_artifact_id"] is None
        and seal_verified and tamper_detected and resealed["new_artifact_id"] != tamper["header"]["artifact_id"],
        "good_violations": good_v,
        "bad_violations": bad_v,
        "minor": minor_ok,
        "enum": enum_major_required,
        "terminal_ok": terminal_ok,
        "terminal_fail": terminal_fail,
        "seal_ok": seal_verified,
        "tamper_detected": tamper_detected,
        "resealed_id": resealed["new_artifact_id"],
    }


def demo_c7_adapters(harness: Path) -> dict:
    vl = ValidationAdapter(layer="L2")
    ok_wire = vl.run({"layer": "L2", "state": "passed", "detail": "structural only"})
    fail_closed = False
    try:
        vl.run({"layer": "L2", "state": "passed", "failure_class": "CRITICAL"})
    except _stubs.UnpinnedSemanticError:
        fail_closed = True

    no = NormalizerAdapter()
    ok_no = no.run({"self_assessment": 0.6, "sufficiency": 0.8, "validation_state": "passed", "validation_flags": []})
    fifth_blocked = False
    try:
        no.run({"self_assessment": 0.6, "sufficiency": 0.8, "validation_state": "passed", "validation_flags": [], "analyst_selected_pass": True})
    except _stubs.UnpinnedSemanticError:
        fifth_blocked = True
    contrad_blocked = False
    try:
        no.run({"self_assessment": 0.6, "sufficiency": 0.8, "validation_state": "contradicted", "validation_flags": []})
    except _stubs.UnpinnedSemanticError:
        contrad_blocked = True
    return {
        "ok": ok_wire["ok"] and fail_closed and ok_no["ok"] and not ok_no["model_called"] and fifth_blocked and contrad_blocked,
        "vl_wire": ok_wire,
        "vl_fail_closed_on_fc_value": fail_closed,
        "no_ok": ok_no,
        "no_fifth_input_blocked": fifth_blocked,
        "no_contradicted_from_caller_blocked": contrad_blocked,
    }


def demo_c8_metering(harness: Path) -> dict:
    from ec8wave1.ledger import Ledger
    from ec8wave1.provider import MockProvider, ProviderCall

    ledger = Ledger(harness / "c8_ledger.jsonl")
    ledger._reset_file()
    provider = MockProvider(ledger, backoff_seconds=(0.0, 0.0))
    adapter = ValidationAdapter(layer="L2")
    adapter.bind_provider(provider)
    call = ProviderCall(
        model_id="deepseek.v3.2",
        component="validation_l2",
        run_id="R-METER",
        layer="L2",
        source="mock.bedrock-mantle.local",
        analyst_slot="s01",
        prompt="adapter-routed validation call",
        max_attempts=2,
        request_meta={"run_context": "Morning", "call_point": 901, "ordinal_in_context": 1},
    )
    res = adapter.submit_execution(call)
    rows = ledger.read_all()
    no_caller_ledger_writes = all(r.get("kind") == "provider_call" for r in rows)
    return {
        "ok": res["status"] == "ok" and len(rows) >= 1 and no_caller_ledger_writes,
        "status": res["status"],
        "ledger_rows": len(rows),
        "outcomes": [r["outcome"] for r in rows],
        "meter_lives_at_execution_point": no_caller_ledger_writes,
    }


def demo_c9_semantic(harness: Path) -> dict:
    pkg = WAVE2_ROOT / "ec8wave2"
    net_re = re.compile(r"^\s*(import|from)\s+(socket|requests|urllib|httpx|http\.client|aiohttp|urllib3)(\s|\.|$)", re.M)
    default_re = [
        re.compile(r"state\s*[=:]\s*[\"']pass[\"']"),
        re.compile(r"[\"'](?:state|validation_state)[\"']\s*:\s*[\"']contradicted[\"']"),
        re.compile(r"failure_class\s*=\s*[\"']"),
        re.compile(r"test_id\s*=\s*[\"']"),
        re.compile(r"ran_n\s*=\s*\d+"),
        re.compile(r"analyst_selected_pass\s*[=:]"),
    ]
    net_hits = []
    default_hits: dict[str, int] = {}
    for fname in PROD_MODULES:
        text = (pkg / fname).read_text(encoding="utf-8")
        for m in net_re.finditer(text):
            net_hits.append(f"{fname}:{m.group(0).strip()}")
        for i, rx in enumerate(default_re):
            hits = len(rx.findall(text))
            if hits:
                default_hits[f"pattern_{i}"] = default_hits.get(f"pattern_{i}", 0) + hits
    banned_helpers = []
    for fname in PROD_MODULES:
        text = (pkg / fname).read_text(encoding="utf-8")
        for m in re.finditer(r"^\s*def\s+([a-zA-Z_0-9]+)\s*\(", text, re.M):
            if any(t in m.group(1).lower() for t in ("promote", "override", "auto_exclude", "default_fc", "default_gap")):
                banned_helpers.append(f"{fname}:{m.group(1)}")
    return {
        "ok": not net_hits and not default_hits and not banned_helpers,
        "network_imports": net_hits,
        "semantic_default_pattern_hits": default_hits,
        "banned_helper_functions": banned_helpers,
    }


def demo_c10_secret(harness: Path) -> dict:
    from ec8wave1.ledger import Ledger
    from ec8wave1.provider import MockProvider, ProviderCall

    fixture_secret = os.environ.get("EC8_W0_FIXTURE_SECRET", "w0-audition-secret-not-for-store")
    live_secret = os.environ.get("AWS_BEARER_TOKEN_BEDROCK")
    ledger = Ledger(harness / "c10_ledger.jsonl")
    ledger._reset_file()
    provider = MockProvider(ledger, backoff_seconds=(0.0, 0.0))
    provider.execute(ProviderCall("deepseek.v3.2", "analyst_s1", "R-SEC", "analyst", "mock.local", prompt="secret-scan fixture", max_attempts=1))

    note = harness / "c10_note.jsonl"
    note.write_text(json.dumps({"note": "disposable-only fixture"}), encoding="utf-8")
    files = [ledger.path, note]
    fixture_hits = 0
    live_hits = 0
    for f in files:
        if f.exists():
            text = f.read_text(encoding="utf-8", errors="ignore")
            fixture_hits += text.count(fixture_secret)
            if live_secret:
                live_hits += text.count(live_secret)

    has_update = hasattr(Ledger, "update") or hasattr(CheckpointStore, "update") or hasattr(Registry, "update")
    has_delete = hasattr(Ledger, "delete") or hasattr(CheckpointStore, "delete") or hasattr(Registry, "delete")
    return {
        "ok": fixture_hits == 0 and live_hits == 0 and not has_update and not has_delete,
        "fixture_hits": fixture_hits,
        "live_token_hits": live_hits,
        "files_scanned": [str(f) for f in files],
        "mutate_delete_api_present": {"update": has_update, "delete": has_delete},
    }


def demo_x1_contamination(harness: Path) -> dict:
    import random

    prog = CanaryProgram("R-CAN")
    prog.inject("A")
    prog.inject("B")
    b_canary = prog.owners()["B"][0]
    a_canary = prog.owners()["A"][0]
    outputs = {
        "A": [f"analysis text for A {b_canary}"],
        "B": [f"clean analysis for B, no foreign token, {a_canary} placed nowhere"],
    }
    events = prog.cross_scan(outputs)
    contaminated = [e for e in events if e["owner"] == "B" and e["found_in"] == "A"]
    stripped = CanaryProgram.strip("prefix " + b_canary + " suffix")
    finger = Fingerprinter(threshold=0.85)
    dup = "the same line of analyst text repeated verbatim across two outputs " * 8
    flags = finger.check({"A": dup, "B": dup})
    flags_not_auto = all(f["action"] == "investigate" and f["auto_exclusion"] is False for f in flags)
    sampler = PairwiseSampler()
    pairs = sampler.select(["A", "B", "C", "D"], rng=random.Random(7))
    return {
        "ok": len(contaminated) >= 1 and "EC8C_" not in stripped and flags_not_auto and len(pairs) >= 1,
        "contamination_events": events,
        "stripped_contains_canary": "EC8C_" in stripped,
        "fingerprint_flags": flags,
        "pairwise_pairs": pairs,
    }


def demo_x2_fallback(harness: Path) -> dict:
    from ec8wave1.ledger import Ledger
    from ec8wave1.provider import MockProvider, ProviderCall

    ledger = Ledger(harness / "x2_ledger.jsonl")
    ledger._reset_file()
    primary = MockProvider(ledger, backoff_seconds=(0.0, 0.0))
    fallback = MockProvider(ledger, backoff_seconds=(0.0, 0.0))
    primary.program_terminal(600)
    fb = FallbackProvider(primary=primary, fallback=fallback)
    call = ProviderCall(
        model_id="mistral.mistral-large-3-675b-instruct",
        component="validation_l3",
        run_id="R-FB",
        layer="L3",
        source="mock.bedrock-mantle.local",
        prompt="l3 fallback demo",
        max_attempts=1,
        request_meta={"call_point": 600},
    )
    res1 = fb.execute(call)
    switched = len(fb.switch_events) == 1 and fb.switch_events[0]["trigger"] == "primary_execution_failure"
    res2 = fb.execute(call)
    stayed = res2["status"] == "ok" and len(fb.switch_events) == 1

    ledger2 = Ledger(harness / "x2_ledger2.jsonl")
    ledger2._reset_file()
    p2 = MockProvider(ledger2, backoff_seconds=(0.0, 0.0))
    f2 = MockProvider(ledger2, backoff_seconds=(0.0, 0.0))
    p2.program_terminal(601)
    f2.program_terminal(601)
    fb2 = FallbackProvider(primary=p2, fallback=f2)
    call601 = ProviderCall(
        model_id="mistral.mistral-large-3-675b-instruct",
        component="validation_l3",
        run_id="R-FB2",
        layer="L3",
        source="mock.bedrock-mantle.local",
        prompt="l3 both-fail demo",
        max_attempts=1,
        request_meta={"call_point": 601},
    )
    res_blocked = fb2.execute(call601)
    entry = {"family_id": "claude", "provider_org": "anthropic", "model_id": "haiku", "version_id": "v1", "capability_classes": ["l3_fallback"], "status": "fixture"}
    elig = registry_entry_eligible(entry, "haiku")
    return {
        "ok": switched and stayed and res_blocked["status"] == "blocked" and elig["eligible"] and not elig["approval_assumed"],
        "res1": res1["status"],
        "switch_events": fb.switch_events,
        "res2": res2["status"],
        "both_failed": res_blocked["status"],
        "eligibility": elig,
    }


def run_all_demos(harness: Path) -> dict:
    demos = {
        "C1": demo_c1_isolation,
        "C2": demo_c2_session,
        "C3": demo_c3_chokepoint,
        "C4": demo_c4_registry,
        "C5": demo_c5_checkpoint,
        "C6": demo_c6_artifact,
        "C7": demo_c7_adapters,
        "C8": demo_c8_metering,
        "C9": demo_c9_semantic,
        "C10": demo_c10_secret,
        "X1": demo_x1_contamination,
        "X2": demo_x2_fallback,
    }
    out = {}
    for cid, fn in demos.items():
        result = fn(harness)
        out[cid] = {"ok": bool(result.get("ok")), **{k: v for k, v in result.items() if k != "ok"}}
        print(f"{cid}: {'PASS' if result.get('ok') else 'FAIL'}")
    return out
