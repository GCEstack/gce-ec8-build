"""Phase 1 — WS1 schema acceptance (G1).

Golden-fixture round-trip for all ten contracts plus envelope consistency and
fail-closed negative cases.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from ecai.schemas import (
    CONTRACTS,
    ENVELOPE_SCHEMA_ID,
    SchemaValidationError,
    load_schema,
    resolved_schema,
    schema_names,
    validate,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "golden"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def test_contract_set_complete():
    # ten contract schemas + the canonical envelope definition.
    assert len(CONTRACTS) == 10
    assert set(CONTRACTS) <= set(schema_names())
    assert set(schema_names()) == set(CONTRACTS) | {"common_envelope"}


@pytest.mark.parametrize("name", CONTRACTS)
def test_schema_is_valid_draft_2020_12(name):
    Draft202012Validator.check_schema(resolved_schema(name))


@pytest.mark.parametrize("name", CONTRACTS)
def test_resolved_schema_has_no_cross_file_refs(name):
    """All cross-file refs are inlined into local `$defs` by the loader."""

    def refs(node):
        found = []
        if isinstance(node, dict):
            if isinstance(node.get("$ref"), str):
                found.append(node["$ref"])
            for value in node.values():
                found.extend(refs(value))
        elif isinstance(node, list):
            for value in node:
                found.extend(refs(value))
        return found

    for ref in refs(resolved_schema(name)):
        assert not ref.startswith("ecai/"), (name, ref)


@pytest.mark.parametrize("name", CONTRACTS)
def test_golden_fixture_validates(name):
    validate(_fixture(name), name)


def test_envelope_schema_accepts_fixture_envelope():
    fixture = _fixture("binding_record")
    validate(
        {k: fixture[k] for k in ("schema_id", "run_id", "produced_at", "provenance")},
        ENVELOPE_SCHEMA_ID,
    )


def test_envelope_consistency_across_contracts():
    """Every contract must inline the same envelope property/required surface."""
    reference = load_schema("common_envelope")
    ref_props = set(reference["properties"])
    ref_required = set(reference["required"])
    ref_prov = reference["properties"]["provenance"]

    for name in CONTRACTS:
        schema = load_schema(name)
        assert ref_required <= set(schema["required"]), name
        for key in ref_props:
            assert key in schema["properties"], (name, key)
        prov = schema["properties"]["provenance"]
        assert set(ref_prov["required"]) <= set(prov["required"]), name
        assert set(prov["properties"]) == set(ref_prov["properties"]), name
        assert prov["additionalProperties"] is False, name


@pytest.mark.parametrize("name", CONTRACTS)
def test_missing_envelope_field_is_rejected(name):
    fixture = _fixture(name)
    del fixture["provenance"]
    with pytest.raises(SchemaValidationError):
        validate(fixture, name)


@pytest.mark.parametrize("name", CONTRACTS)
def test_unknown_field_is_rejected(name):
    fixture = _fixture(name)
    fixture["__unexpected__"] = True
    with pytest.raises(SchemaValidationError):
        validate(fixture, name)


def test_panel_stage_requires_persona():
    fixture = _fixture("analyst_verdict")
    fixture["provenance"].pop("persona")
    with pytest.raises(SchemaValidationError):
        validate(fixture, "analyst_verdict")


def test_no_data_must_have_null_selection():
    fixture = _fixture("analyst_verdict")
    fixture["verdict"] = "NO_DATA"
    with pytest.raises(SchemaValidationError):
        validate(fixture, "analyst_verdict")


def test_directional_verdict_requires_selection_and_rationale():
    fixture = _fixture("analyst_verdict")
    fixture["rationale"] = []
    with pytest.raises(SchemaValidationError):
        validate(fixture, "analyst_verdict")


def test_gatekeeper_response_has_no_mutation_fields():
    """T-08 (schema half): no pick/selection/score/numeric override field exists."""
    props = set(load_schema("gatekeeper_response")["properties"])
    for banned in (
        "pick",
        "selection",
        "direction",
        "score",
        "confidence",
        "confidence_hint",
        "line_value",
        "stake",
    ):
        assert banned not in props, banned
    assert load_schema("gatekeeper_response")["additionalProperties"] is False


def test_gatekeeper_response_rejects_injected_pick():
    fixture = _fixture("gatekeeper_response")
    fixture["pick"] = "HOME"
    with pytest.raises(SchemaValidationError):
        validate(fixture, "gatekeeper_response")


def test_det_output_has_no_lean_fields():
    props = set(load_schema("det_output")["properties"])
    for banned in ("pick", "selection", "direction", "score", "recommendation"):
        assert banned not in props, banned


def test_evidence_factor_enum_excludes_consensus_and_kalshi():
    enum = set(load_schema("evidence_item")["properties"]["factor"]["enum"])
    assert "consensus" not in enum
    assert "kalshi" not in enum
    assert enum == {
        "pitchers", "bullpen", "lineups", "umpire", "weather",
        "rest", "injuries", "team_evidence", "odds_betmgm",
    }
