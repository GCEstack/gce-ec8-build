"""Phase 2 — WS2 DET lane acceptance: sufficiency states (§3.5), no-lean, versioned registry."""

from __future__ import annotations

from pathlib import Path

import pytest

from ecai.binding import bind
from ecai.detlane import compute_sufficiency, load_det_config, run_det, run_det_slate
from ecai.framing import FACTOR_WHITELIST, frame_slate
from ecai.schemas import load_schema, validate

FREEZE = Path(
    r"C:\Users\Dekan AI Brother\Desktop\mlb-data-system"
    r"\EC8_MLB_COMMON_FROZEN_DATASET_2026-09-15_EARLYCLUSTER-FROZEN-v1"
)
CRITICAL = ["pitchers", "lineups", "odds_betmgm"]

real_freeze = pytest.mark.skipif(not FREEZE.is_dir(), reason="frozen dataset not present")


def _framing(available: dict[str, bool] | None = None, *, rows: dict | None = None) -> dict:
    available = available or {}
    rows = rows or {}
    factors = {
        name: {
            "available": available.get(name, True),
            "source_relpath": f"frozen/{name}.csv",
            "source_sha256": "a" * 64,
            "rows": rows.get(name, []),
        }
        for name in FACTOR_WHITELIST
    }
    return {
        "schema_id": "ecai/framing_object/1.0",
        "run_id": "11111111-1111-4111-8111-111111111111",
        "produced_at": "2026-09-15T22:10:00Z",
        "provenance": {
            "stage": "FRAMING", "persona": None, "model_id": None,
            "input_artifact_hashes": [],
        },
        "game_key": "Away@Home 2026-09-15",
        "slate_date": "2026-09-15",
        "first_pitch_pt": "15:40",
        "market_scope": "moneyline",
        "factors": factors,
        "missing_factors": [n for n in FACTOR_WHITELIST if not factors[n]["available"]],
    }


# --------------------------------------------------------------------------- sufficiency
def test_all_available_is_sufficient():
    assert compute_sufficiency(_framing()["factors"], CRITICAL) == "SUFFICIENT"


def test_one_noncritical_missing_is_sparse():
    assert compute_sufficiency(
        _framing({"injuries": False})["factors"], CRITICAL
    ) == "SPARSE"


def test_one_critical_missing_is_sparse():
    assert compute_sufficiency(
        _framing({"pitchers": False})["factors"], CRITICAL
    ) == "SPARSE"


def test_two_critical_missing_is_insufficient():
    assert compute_sufficiency(
        _framing({"pitchers": False, "lineups": False})["factors"], CRITICAL
    ) == "INSUFFICIENT"


def test_low_coverage_is_insufficient():
    available = {name: False for name in ("bullpen", "umpire", "weather", "rest")}
    assert compute_sufficiency(_framing(available)["factors"], CRITICAL) == "INSUFFICIENT"


# --------------------------------------------------------------------------- DET output
def test_det_output_validates_and_is_versioned():
    det = run_det(_framing())
    validate(det, "ecai/det_output/1.0")
    assert det["det_checks_version"] == load_det_config()["det_checks_version"]
    assert det["data_sufficiency"] == "SUFFICIENT"
    assert det["provenance"]["stage"] == "DET"
    assert det["provenance"]["input_artifact_hashes"]


def test_det_output_has_no_lean_fields():
    props = set(load_schema("det_output")["properties"])
    for banned in ("pick", "selection", "direction", "score", "recommendation", "confidence"):
        assert banned not in props
    det = run_det(_framing())
    assert set(det) == set(load_schema("det_output")["required"])


def test_check_registry_is_versioned_and_well_formed():
    config = load_det_config()
    assert config["det_checks_version"]
    assert config["checks"]
    for check in config["checks"]:
        assert check["check_id"]
        assert check["rule"]
        assert check["factor"] in FACTOR_WHITELIST


def test_det_reports_sparse_on_critical_missing():
    det = run_det(_framing({"lineups": False}))
    assert det["data_sufficiency"] == "SPARSE"
    by_id = {c["check_id"]: c for c in det["checks"]}
    assert by_id["LINEUPS_AVAILABLE"]["result"] == "FAIL"
    assert by_id["LINEUPS_COMPLETE"]["result"] == "NOT_EVALUABLE"


def test_both_teams_present_and_lineups_complete():
    rows = {
        "lineups": [{"team": "Away"} for _ in range(9)] + [{"team": "Home"} for _ in range(9)],
        "pitchers": [{"team": "Away"}, {"team": "Home"}],
    }
    det = run_det(_framing(rows=rows))
    by_id = {c["check_id"]: c for c in det["checks"]}
    assert by_id["LINEUPS_COMPLETE"]["result"] == "PASS"
    assert by_id["PITCHERS_BOTH_SIDES"]["result"] == "PASS"

    short = {"lineups": [{"team": "Away"} for _ in range(9)]}
    det_short = run_det(_framing(rows=short))
    by_id_short = {c["check_id"]: c for c in det_short["checks"]}
    assert by_id_short["LINEUPS_COMPLETE"]["result"] == "FAIL"


# --------------------------------------------------------------------------- real freeze
@real_freeze
def test_det_slate_on_real_freeze():
    binding = bind(FREEZE, expect_slate="2026-09-15")
    framed = frame_slate(FREEZE, binding)
    dets = run_det_slate(framed)
    assert len(dets) == 12
    for det in dets:
        validate(det, "ecai/det_output/1.0")
        assert det["data_sufficiency"] in {"SUFFICIENT", "SPARSE", "INSUFFICIENT"}
        assert det["det_checks_version"] == load_det_config()["det_checks_version"]
        assert all(
            c["result"] in {"PASS", "FAIL", "NOT_EVALUABLE"} for c in det["checks"]
        )
