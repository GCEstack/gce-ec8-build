"""WS5 — binder/framer (P20 §2.2, §3.1).

Source-only framing: transcode the raw frozen BetMGM-scope values into a
`framing_object/1.0` per eligible game. No derived stats, no DET output, no
consensus/Kalshi, no other books. The framer never opens `consensus_*.csv` or
`kalshi_*.csv` — they are absent from the factor whitelist by construction.
"""

from __future__ import annotations

import csv
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ..binding.verify import sha256_file
from ..schemas import validate
from . import redaction as R

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
DEFAULT_MARKETS_CONFIG = CONFIG_DIR / "markets.yaml"

FRAMING_SCHEMA = "ecai/framing_object/1.0"

# factor -> (source filename prefix under frozen/, raw column whitelist)
FACTOR_SPECS: dict[str, dict[str, Any]] = {
    "pitchers": {
        "prefix": "pitchers_",
        "keyed": "game",
        "columns": (
            "pitcher", "team", "throws", "era_season", "whip_season", "k9_season",
            "bb9_season", "hr9_season", "era_home", "whip_home", "era_away",
            "whip_away", "vs_opp_era", "vs_opp_whip", "vs_opp_innings", "days_rest",
            "last_start_date", "last_start_ip", "last_start_er", "last_start_k",
            "last_start_within_7d", "season_innings_pitched",
        ),
    },
    "bullpen": {
        "prefix": "bullpen_",
        "keyed": "game",
        "columns": (
            "team", "pitcher", "apps_3d", "innings_3d", "pitches_3d",
            "save_opp_7d", "blown_saves_7d", "season_innings_pitched",
        ),
    },
    "lineups": {
        "prefix": "lineups_",
        "keyed": "game",
        "columns": (
            "team", "batting_order", "player", "bats",
            "ops_vs_rhp", "ops_vs_lhp", "last7_avg", "last7_ops",
        ),
    },
    "umpire": {
        "prefix": "umpires_",
        "keyed": "game",
        "columns": (
            "umpire_home_plate", "games_called", "k_per_game",
            "bb_per_game", "runs_per_game", "hits_per_game",
        ),
    },
    "weather": {
        "prefix": "weather_",
        "keyed": "game",
        "columns": (
            "venue", "roof_status", "temp_f", "wind_speed_mph", "wind_direction",
            "precipitation_chance", "humidity_pct", "conditions",
        ),
    },
    "rest": {
        "prefix": "rest_",
        "keyed": "game",
        "columns": (
            "team", "days_rest", "travel_miles", "day_after_night",
            "extra_innings_yesterday", "bullpen_ip_yesterday",
        ),
    },
    "injuries": {
        "prefix": "injuries_",
        "keyed": "team",
        "columns": (
            "team", "player", "status", "expected_return",
            "injury_type", "impact_note", "reported_at",
        ),
    },
    "team_evidence": {
        "prefix": "team_evidence_",
        "keyed": "team",
        "columns": (
            "team", "team_ops", "bullpen_era", "n_relievers",
            "bullpen_innings_pitched",
        ),
    },
    # odds_betmgm columns are scope-driven (BetMGM columns only); see _build_odds.
    "odds_betmgm": {"prefix": "odds_", "keyed": "game", "columns": ()},
}

_MISSING = {None, "", "NOT_SET", "UNAVAILABLE"}
_ODDS_COLUMNS = ("market", "selection", "status", "fetched_at")


class FramingError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(game_key: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", game_key).strip("_")


def split_game_key(game_key: str) -> tuple[str, str]:
    """`"Away@Home YYYY-MM-DD"` → `(away, home)`."""
    left, _, rest = game_key.partition("@")
    away = left.strip()
    home = rest.rsplit(" ", 1)[0].strip() if rest.strip() else ""
    return away, home


def load_markets_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path else DEFAULT_MARKETS_CONFIG
    with open(config_path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def scope_config(markets: dict[str, Any], scope: str) -> dict[str, Any]:
    try:
        return markets["scopes"][scope]
    except KeyError as exc:
        raise FramingError(f"unregistered market_scope: {scope}") from exc


def _read_csv(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _resolve_source(dataset_root: Path, prefix: str) -> Path:
    matches = sorted((dataset_root / "frozen").glob(f"{prefix}*.csv"))
    if len(matches) != 1:
        raise FramingError(
            f"expected exactly one frozen/{prefix}*.csv, found {len(matches)}"
        )
    return matches[0]


def _relpath(dataset_root: Path, path: Path) -> str:
    return path.relative_to(dataset_root).as_posix()


def _factor_object(
    *, available: bool, relpath: str, sha256: str, rows: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "available": available,
        "source_relpath": relpath,
        "source_sha256": sha256,
        "rows": rows,
    }


def _build_game_factor(
    table: list[dict[str, str]], game_key: str, columns: tuple[str, ...]
) -> list[dict[str, Any]]:
    return [
        R.project_columns(row, columns)
        for row in table
        if row.get("game") == game_key
    ]


def _build_odds(
    table: list[dict[str, str]], game_key: str, scope: dict[str, Any]
) -> tuple[list[dict[str, Any]], bool]:
    price_col = scope["source_columns"]["price"]
    line_col = scope["source_columns"]["line"]
    market = scope["odds_market"]
    columns = _ODDS_COLUMNS + (price_col, line_col)
    rows = [
        R.project_columns(row, columns)
        for row in table
        if row.get("game") == game_key and row.get("market") == market
    ]
    available = any(row.get(price_col) not in _MISSING for row in rows)
    return rows, available


def _first_pitch_map(dataset_root: Path) -> dict[str, str]:
    path = _resolve_source(dataset_root, "FROZEN_GAMES_")
    return {
        row["game"]: row["first_pitch_pt"]
        for row in _read_csv(path)
        if row.get("game")
    }


def build_framing_object(
    dataset_root: str | Path,
    binding: Any,
    game_key: str,
    *,
    tables: dict[str, list[dict[str, str]]],
    sources: dict[str, Path],
    source_hashes: dict[str, str],
    first_pitch_pt: str,
    scope_name: str,
    scope: dict[str, Any],
    input_artifact_hashes: list[str],
    run_id: str,
) -> dict[str, Any]:
    dataset_root = Path(dataset_root)
    away, home = split_game_key(game_key)

    factors: dict[str, Any] = {}
    for factor, spec in FACTOR_SPECS.items():
        relpath = _relpath(dataset_root, sources[factor])
        sha = source_hashes[factor]
        if factor == "odds_betmgm":
            rows, available = _build_odds(tables[factor], game_key, scope)
        elif spec["keyed"] == "team":
            rows = [
                R.project_columns(row, spec["columns"])
                for row in tables[factor]
                if row.get("team") in (away, home)
            ]
            available = len(rows) > 0
        else:
            rows = _build_game_factor(tables[factor], game_key, spec["columns"])
            available = len(rows) > 0
            if factor == "umpire" and rows:
                available = rows[0].get("umpire_home_plate") not in _MISSING
            elif factor == "weather" and rows:
                available = (
                    rows[0].get("temp_f") not in _MISSING
                    or rows[0].get("roof_status") == "CLOSED"
                )
        factors[factor] = _factor_object(
            available=available, relpath=relpath, sha256=sha, rows=rows
        )

    R.assert_factor_keys(factors)

    payload: dict[str, Any] = {
        "schema_id": FRAMING_SCHEMA,
        "run_id": run_id,
        "produced_at": _utc_now(),
        "provenance": {
            "stage": "FRAMING",
            "persona": None,
            "model_id": None,
            "input_artifact_hashes": list(input_artifact_hashes),
        },
        "game_key": game_key,
        "slate_date": binding.slate_date,
        "first_pitch_pt": first_pitch_pt,
        "market_scope": scope_name,
        "factors": factors,
        "missing_factors": [
            factor for factor in R.FACTOR_WHITELIST if not factors[factor]["available"]
        ],
    }
    R.assert_framing_redacted(payload)
    return payload


def frame_slate(
    dataset_root: str | Path,
    binding: Any,
    *,
    market_scope: str | None = None,
    run_id: str | None = None,
    out_root: str | Path | None = None,
    markets_config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Frame every eligible game in the bound freeze (source-only, fail-closed)."""
    root = Path(dataset_root)
    markets = markets_config or load_markets_config()
    scope_name = market_scope or markets["default_scope"]
    scope = scope_config(markets, scope_name)
    run = run_id or str(uuid.uuid4())

    sources: dict[str, Path] = {}
    source_hashes: dict[str, str] = {}
    for factor, spec in FACTOR_SPECS.items():
        path = _resolve_source(root, spec["prefix"])
        R.assert_source_allowed(_relpath(root, path))
        sources[factor] = path
        source_hashes[factor] = sha256_file(path)

    tables = {factor: _read_csv(path) for factor, path in sources.items()}
    first_pitches = _first_pitch_map(root)
    input_hashes = [binding.composite_digest] + sorted(set(source_hashes.values()))

    framed: list[dict[str, Any]] = []
    for game_key in binding.eligible_games:
        first_pitch_pt = first_pitches.get(game_key)
        if not first_pitch_pt:
            raise FramingError(f"no frozen first pitch for eligible game: {game_key}")
        payload = build_framing_object(
            root,
            binding,
            game_key,
            tables=tables,
            sources=sources,
            source_hashes=source_hashes,
            first_pitch_pt=first_pitch_pt,
            scope_name=scope_name,
            scope=scope,
            input_artifact_hashes=input_hashes,
            run_id=run,
        )
        validate(payload, FRAMING_SCHEMA)
        if out_root is not None:
            run_dir = Path(out_root) / run / "framing"
            run_dir.mkdir(parents=True, exist_ok=True)
            import json

            (run_dir / f"{slugify(game_key)}.json").write_text(
                json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
                encoding="utf-8",
            )
        framed.append(payload)

    return framed
