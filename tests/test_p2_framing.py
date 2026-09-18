"""Phase 2 — WS5 framing acceptance: T-01 (source-only) + T-14 (consensus/Kalshi exclusion)."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pytest

from ecai.binding import bind
from ecai.framing import frame_slate, load_markets_config, split_game_key
from ecai.framing import redaction as R
from ecai.schemas import validate

FREEZE = Path(
    r"C:\Users\Dekan AI Brother\Desktop\mlb-data-system"
    r"\EC8_MLB_COMMON_FROZEN_DATASET_2026-09-15_EARLYCLUSTER-FROZEN-v1"
)
BUILD_ROOT = Path(__file__).resolve().parent.parent
FRAMING_TOP_KEYS = {
    "schema_id", "run_id", "produced_at", "provenance",
    "game_key", "slate_date", "first_pitch_pt", "market_scope",
    "factors", "missing_factors",
}
ODDS_KEYS = {"market", "selection", "betmgm", "betmgm_line", "status", "fetched_at"}
OTHER_BOOKS = ("draftkings", "fanduel", "bovada", "espnbet", "betrivers")

real_freeze = pytest.mark.skipif(not FREEZE.is_dir(), reason="frozen dataset not present")


@pytest.fixture(scope="module")
def framed():
    binding = bind(FREEZE, expect_slate="2026-09-15")
    return frame_slate(FREEZE, binding)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


# --------------------------------------------------------------------------- T-01
@real_freeze
def test_t01_framing_object_has_only_whitelisted_keys(framed):
    assert len(framed) == 12
    for obj in framed:
        assert set(obj) == FRAMING_TOP_KEYS, obj["game_key"]
        assert set(obj["factors"]) == set(R.FACTOR_WHITELIST)
        assert obj["schema_id"] == "ecai/framing_object/1.0"
        validate(obj, "ecai/framing_object/1.0")


@real_freeze
def test_t01_pitcher_values_match_frozen_csv(framed):
    raw = _read_csv(next((FREEZE / "frozen").glob("pitchers_*.csv")))
    for obj in framed:
        game = obj["game_key"]
        expected = [
            {k: row[k] for k in obj["factors"]["pitchers"]["rows"][0]}
            for row in raw
            if row["game"] == game
        ]
        assert obj["factors"]["pitchers"]["rows"] == expected


@real_freeze
def test_t01_lineup_values_match_frozen_csv(framed):
    raw = _read_csv(next((FREEZE / "frozen").glob("lineups_*.csv")))
    obj = framed[0]
    expected = [
        {k: row[k] for k in obj["factors"]["lineups"]["rows"][0]}
        for row in raw
        if row["game"] == obj["game_key"]
    ]
    assert obj["factors"]["lineups"]["rows"] == expected


@real_freeze
def test_t01_missing_factors_consistent_with_availability(framed):
    for obj in framed:
        unavailable = {
            name for name, factor in obj["factors"].items() if not factor["available"]
        }
        assert set(obj["missing_factors"]) == unavailable


@real_freeze
def test_t01_factor_refs_are_frozen_and_hashed(framed):
    for obj in framed:
        for name, factor in obj["factors"].items():
            assert factor["source_relpath"].startswith("frozen/")
            assert len(factor["source_sha256"]) == 64


@real_freeze
def test_market_scope_travels(framed):
    assert {obj["market_scope"] for obj in framed} == {"moneyline"}
    assert load_markets_config()["default_scope"] == "moneyline"


# --------------------------------------------------------------------------- T-14
def test_t14_reasoning_path_has_no_consensus_or_kalshi_source_refs():
    """Grep-gate: no reasoning-path module names a consensus/Kalshi source file."""
    csv_literal = re.compile(r"""["']([^"']*\.csv)["']""")
    modules = list((BUILD_ROOT / "ecai" / "framing").glob("*.py")) + list(
        (BUILD_ROOT / "ecai" / "detlane").glob("*.py")
    )
    assert modules
    for module in modules:
        for literal in csv_literal.findall(module.read_text(encoding="utf-8")):
            lowered = literal.lower()
            assert "consensus" not in lowered, (module.name, literal)
            assert "kalshi" not in lowered, (module.name, literal)


def test_t14_factor_specs_have_no_forbidden_prefix():
    from ecai.framing import FACTOR_SPECS

    for spec in FACTOR_SPECS.values():
        assert not R.is_forbidden_source(spec["prefix"])


def test_t14_factor_whitelist_excludes_consensus_and_kalshi():
    assert "consensus" not in R.FACTOR_WHITELIST
    assert "kalshi" not in R.FACTOR_WHITELIST
    assert R.is_forbidden_source("frozen/consensus_2026-09-15.csv")
    assert R.is_forbidden_source("frozen/kalshi_markets_2026-09-15.csv")
    with pytest.raises(R.RedactionViolation):
        R.assert_source_allowed("frozen/kalshi_markets_2026-09-15.csv")


@real_freeze
def test_t14_framing_values_contain_no_consensus_or_kalshi(framed):
    blob = json.dumps(framed).lower()
    assert "consensus" not in blob
    assert "kalshi" not in blob


@real_freeze
def test_t14_odds_betmgm_uses_only_betmgm_columns(framed):
    for obj in framed:
        for row in obj["factors"]["odds_betmgm"]["rows"]:
            assert set(row) <= ODDS_KEYS
            for book in OTHER_BOOKS:
                assert book not in row


@real_freeze
def test_redaction_rejects_non_source_only_top_level_key():
    with pytest.raises(R.RedactionViolation):
        R.assert_framing_redacted({"game_key": "x", "pick": "HOME"})


# --------------------------------------------------------------------------- scope config
def test_scope_config_rejects_unregistered_scope():
    from ecai.framing import FramingError, scope_config

    with pytest.raises(FramingError):
        scope_config(load_markets_config(), "not-a-scope")


def test_split_game_key():
    away, home = split_game_key("Los Angeles Dodgers@Cincinnati Reds 2026-09-15")
    assert away == "Los Angeles Dodgers"
    assert home == "Cincinnati Reds"
