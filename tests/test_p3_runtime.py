"""Phase 3 — WS4 runtime acceptance: retry/timeout/quorum units (mocked client),
T-05 path, T-13 substitution logging, raw retention, GK-failure STOP path.

No live Bedrock call is made anywhere in this module.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from ecai.runtime import (
    GATEKEEPER_UNAVAILABLE,
    QUORUM_STOP,
    BedrockConverseClient,
    Occupant,
    ProvenanceLog,
    RetryPolicy,
    RuntimeManifest,
    UndeclaredModelError,
    call_with_retries,
    diff_substitutions,
    evaluate_quorum,
    is_retryable,
    is_timeout,
    load_manifest,
    quorum_decision,
    quorum_requirement,
)
from ecai.runtime import ModelInvocationError, ModelTimeoutError
from ecai.runtime import replay as replay_mod

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "golden"
ANALYST_VERDICT = json.loads((GOLDEN / "analyst_verdict.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- fakes
class FakeClientError(Exception):
    def __init__(self, code: str, status: int = 400):
        self.response = {
            "Error": {"Code": code},
            "ResponseMetadata": {"HTTPStatusCode": status},
        }
        super().__init__(code)


class FakeBedrock:
    """Duck-typed bedrock-runtime client. Items are responses, exceptions, or callables."""

    def __init__(self, items):
        self._items = list(items)
        self.calls = 0

    def converse(self, **kwargs):
        self.calls += 1
        item = self._items.pop(0)
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            return item(kwargs)
        return item


def tool_response(payload):
    return {
        "output": {
            "message": {
                "content": [{"toolUse": {"name": "ecai_output", "input": payload}}]
            }
        }
    }


def _manifest_with_roster(size: int) -> RuntimeManifest:
    occupant = Occupant(
        model_id="m.analyst", family="f", personas=tuple(f"p{i}" for i in range(size))
    )
    return RuntimeManifest(
        manifest_version="test/1.0", region="us-east-2", analysts=(occupant,),
        gatekeeper=Occupant(model_id="m.gk", family="f"),
        timeout_s=45, max_retries=2, backoff_s=(0, 0), parse_retries=2,
        quorum_fraction=0.67, quorum_floor=2, quorum_window_s=120, raw={},
    )


def _client(items, run_dir, manifest=None):
    return BedrockConverseClient(
        manifest or load_manifest(),
        runtime_client=FakeBedrock(items),
        run_dir=run_dir,
        sleep=lambda _s: None,
    )


def _invoke(client, **overrides):
    kwargs = dict(
        role="analyst", persona="statistician", system="sys",
        user="frame", schema_name="ecai/analyst_verdict/1.0",
    )
    kwargs.update(overrides)
    return client.converse_structured(**kwargs)


# --------------------------------------------------------------------------- manifest
def test_manifest_loads_with_two_plus_families():
    manifest = load_manifest()
    assert manifest.region == "us-east-2"
    assert len(manifest.families()) >= 2
    assert "meta" in manifest.families()
    assert "amazon" in manifest.families()
    assert len(manifest.active_roster()) == 4
    assert manifest.occupant_for_persona("contrarian").family == "amazon"


def test_manifest_pins_confirmed_model_ids():
    manifest = load_manifest()
    assert "anthropic.claude-sonnet-4-5-20250929-v1:0" in manifest.declared_model_ids()
    assert "meta.llama3-3-70b-instruct-v1:0" in manifest.declared_model_ids()
    assert "amazon.nova-pro-v1:0" in manifest.declared_model_ids()


def test_manifest_hash_is_deterministic():
    assert load_manifest().manifest_hash() == load_manifest().manifest_hash()


def test_undeclared_model_is_refused():
    manifest = load_manifest()
    with pytest.raises(UndeclaredModelError):
        manifest.assert_declared("some.undeclared-model")


# --------------------------------------------------------------------------- quorum (T-05 path)
def test_quorum_requirement_floor():
    assert quorum_requirement(3, 0.67, 2) == 3
    assert quorum_requirement(2, 0.67, 2) == 2
    assert quorum_requirement(1, 0.67, 2) == 2


def test_quorum_decision_roster_three():
    manifest = _manifest_with_roster(3)
    assert quorum_decision(3, manifest)["quorum_met"] is True
    below = quorum_decision(2, manifest)
    assert below["quorum_met"] is False
    assert below["status"] == QUORUM_STOP


def test_quorum_decision_roster_one_stops():
    manifest = _manifest_with_roster(1)
    decision = quorum_decision(1, manifest)
    assert decision["requirement"] == 2
    assert decision["quorum_met"] is False
    assert decision["status"] == QUORUM_STOP


def test_evaluate_quorum_uses_manifest_policy():
    manifest = load_manifest()
    assert evaluate_quorum(3, 4, fraction=manifest.quorum_fraction, absolute_floor=2)
    assert not evaluate_quorum(2, 4, fraction=manifest.quorum_fraction, absolute_floor=2)


# --------------------------------------------------------------------------- retry / timeout
def test_retryable_classification():
    assert is_retryable(FakeClientError("ThrottlingException"))
    assert is_retryable(FakeClientError("InternalServerException", 500))
    assert not is_retryable(FakeClientError("ValidationException"))
    assert not is_retryable(TimeoutError("read timed out"))
    assert is_timeout(TimeoutError("read timed out"))


def test_call_with_retries_recovers_on_throttle():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] == 1:
            raise FakeClientError("ThrottlingException")
        return "ok"

    result, retries = call_with_retries(fn, RetryPolicy(45, 2, (0, 0)), sleep=lambda _s: None)
    assert result == "ok"
    assert retries == 1


def test_call_with_retries_exhausts():
    def fn():
        raise FakeClientError("ServiceUnavailableException", 503)

    with pytest.raises(ModelInvocationError):
        call_with_retries(fn, RetryPolicy(45, 2, (0, 0)), sleep=lambda _s: None)


def test_call_with_retries_terminal_error_not_retried():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise FakeClientError("ValidationException")

    with pytest.raises(ModelInvocationError):
        call_with_retries(fn, RetryPolicy(45, 2, (0, 0)), sleep=lambda _s: None)
    assert calls["n"] == 1


def test_timeout_is_terminal_invalid_not_retried():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise TimeoutError("read timed out")

    with pytest.raises(ModelTimeoutError):
        call_with_retries(fn, RetryPolicy(45, 2, (0, 0)), sleep=lambda _s: None)
    assert calls["n"] == 1


# --------------------------------------------------------------------------- structured validation
def test_valid_structured_response(tmp_path):
    client = _client([tool_response(ANALYST_VERDICT)], tmp_path)
    result = _invoke(client)
    assert result.valid is True
    assert result.parsed["verdict"] == "SUPPORTS"
    assert result.parse_retries == 0


def test_parse_failure_retries_then_succeeds(tmp_path):
    bad = {"verdict": "SUPPORTS"}  # missing required fields
    client = _client([tool_response(bad), tool_response(ANALYST_VERDICT)], tmp_path)
    result = _invoke(client)
    assert result.valid is True
    assert result.parse_retries == 1


def test_parse_failure_persists_and_never_bypasses_schema(tmp_path):
    bad = {"verdict": "SUPPORTS"}
    client = _client([tool_response(bad)] * 3, tmp_path)
    result = _invoke(client)
    assert result.valid is False
    assert result.parsed is None
    assert "schema validation failed" in result.error


def test_missing_tool_use_is_invalid(tmp_path):
    client = _client([{"output": {"message": {"content": [{"text": "hi"}]}}}], tmp_path)
    result = _invoke(client)
    assert result.valid is False
    assert result.parsed is None


# --------------------------------------------------------------------------- raw + provenance
def test_raw_retention_and_provenance(tmp_path):
    client = _client([tool_response(ANALYST_VERDICT)], tmp_path)
    _invoke(client)
    raw_files = list((tmp_path / "raw").glob("*.json"))
    assert len(raw_files) == 1
    record = json.loads(raw_files[0].read_text(encoding="utf-8"))
    assert record["stage"] == "analyst_verdict"
    assert record["model_id"] == "anthropic.claude-sonnet-4-5-20250929-v1:0"

    lines = (tmp_path / "provenance.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["kind"] == "invocation"
    assert entry["valid"] is True
    assert entry["substitution"] is False
    assert entry["manifest_hash"]


def test_raw_retained_before_parse_on_invalid(tmp_path):
    bad = {"verdict": "SUPPORTS"}
    client = _client([tool_response(bad)] * 3, tmp_path)
    _invoke(client)
    # one raw file per parse attempt, retained even though parsing failed
    assert len(list((tmp_path / "raw").glob("*.json"))) == 3


def test_provenance_log_is_append_only(tmp_path):
    log = ProvenanceLog(tmp_path)
    log.append({"kind": "invocation", "n": 1})
    log.append({"kind": "invocation", "n": 2})
    entries = log.read_all()
    assert [e["n"] for e in entries] == [1, 2]


# --------------------------------------------------------------------------- substitution (T-13)
def test_diff_substitutions_detects_manifest_change():
    previous = load_manifest()
    changed_analyst = Occupant(
        model_id="amazon.nova-pro-v1:0", family="amazon", personas=("statistician", "market")
    )
    current = replace(
        previous,
        analysts=(
            changed_analyst,
            previous.analysts[1],
            previous.analysts[2],
        ),
    )
    subs = diff_substitutions(previous, current)
    assert any(s["persona"] == "statistician" for s in subs)
    assert all(s["reason"] == "manifest_change" for s in subs)
    assert all(s["substituted_for"] for s in subs)


def test_substitution_is_logged_to_provenance(tmp_path):
    previous = load_manifest()
    current = replace(
        previous,
        gatekeeper=Occupant(model_id="amazon.nova-pro-v1:0", family="amazon"),
    )
    subs = diff_substitutions(previous, current)
    log = ProvenanceLog(tmp_path)
    log.record_substitutions(subs, manifest_hash=current.manifest_hash())
    entries = log.read_all()
    assert entries and entries[0]["kind"] == "substitution"
    assert entries[0]["substituted_for"] == previous.gatekeeper.model_id
    assert entries[0]["reason"] == "manifest_change"


def test_invocation_records_substitution_flag(tmp_path):
    client = _client([tool_response(ANALYST_VERDICT)], tmp_path)
    substitution = {
        "substituted_for": "anthropic.claude-sonnet-4-5",
        "reason": "manifest_change",
    }
    _invoke(client, substitution=substitution)
    entry = json.loads((tmp_path / "provenance.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert entry["substitution"] is True
    assert entry["substituted_for"] == "anthropic.claude-sonnet-4-5"
    assert entry["substitution_reason"] == "manifest_change"


# --------------------------------------------------------------------------- GK failure STOP
def _gk_request():
    return {
        "curated_item": {"ref": "a" * 64, "inline": {"game_key": "Away@Home 2026-09-15"}},
        "binding_digest": "b" * 64,
        "rules_version": "ecai-rules/1.0",
    }


def test_gatekeeper_success(tmp_path):
    response = {
        "schema_id": "ecai/gatekeeper_response/1.0",
        "run_id": "11111111-1111-4111-8111-111111111111",
        "produced_at": "2026-09-15T22:16:00Z",
        "provenance": {
            "stage": "GATEKEEPER", "persona": None,
            "model_id": "anthropic.claude-sonnet-4-5-20250929-v1:0",
            "input_artifact_hashes": [],
        },
        "game_key": "Away@Home 2026-09-15",
        "verdict": "CONFIRM",
        "rationale": [],
        "checks": [{"rule_id": "R-QUORUM", "result": "PASS"}],
    }
    client = _client([tool_response(response)], tmp_path)
    outcome = client.invoke_gatekeeper(request=_gk_request(), run_id="run-1")
    assert outcome.ok is True
    assert outcome.response["verdict"] == "CONFIRM"
    assert outcome.stop is None


def test_gatekeeper_persistent_failure_stops_run(tmp_path):
    client = _client([FakeClientError("ValidationException")] * 3, tmp_path)
    outcome = client.invoke_gatekeeper(request=_gk_request(), run_id="run-1")
    assert outcome.ok is False
    assert outcome.response is None
    assert outcome.stop["status"] == GATEKEEPER_UNAVAILABLE
    assert outcome.stop["run_id"] == "run-1"
    assert outcome.stop["game_key"] == "Away@Home 2026-09-15"
    # a run_stop record is logged; no verdict is fabricated
    entries = [json.loads(x) for x in (tmp_path / "provenance.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(e.get("kind") == "run_stop" and e["status"] == GATEKEEPER_UNAVAILABLE for e in entries)


def test_gatekeeper_schema_invalid_persistent_stops_run(tmp_path):
    bad = {"verdict": "CONFIRM"}  # missing required fields
    client = _client([tool_response(bad)] * 3, tmp_path)
    outcome = client.invoke_gatekeeper(request=_gk_request(), run_id="run-2")
    assert outcome.ok is False
    assert outcome.stop["status"] == GATEKEEPER_UNAVAILABLE


# --------------------------------------------------------------------------- replay surface
def test_replay_full_run_is_deferred_to_phase_6():
    with pytest.raises(replay_mod.ReplayNotAvailable):
        replay_mod.replay_run("run-1")
    assert "run-scoped" in replay_mod.REPLAY_HASH_IMPLICATION


def test_load_recorded_raw_response(tmp_path):
    client = _client([tool_response(ANALYST_VERDICT)], tmp_path)
    _invoke(client)
    path = replay_mod.find_raw_response(tmp_path, stage="analyst_verdict", persona="statistician")
    assert path is not None
    record = replay_mod.load_raw_response(path)
    assert record["response"]["output"]["message"]["content"][0]["toolUse"]
