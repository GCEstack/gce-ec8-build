"""WS2 — deterministic lane (P20 §2.4, §3.5, §7 row 4).

DET emits *facts about data*: a versioned check registry plus a data-sufficiency
state. It structurally emits no pick, score, or recommendation. Critical-factor
membership is config-pinned per market_scope (`config/markets.yaml`).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ..framing.framer import split_game_key, slugify
from ..hashing import sha256_json
from ..schemas import validate

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
DEFAULT_DET_CONFIG = CONFIG_DIR / "det_checks.yaml"
DEFAULT_MARKETS_CONFIG = CONFIG_DIR / "markets.yaml"

DET_SCHEMA = "ecai/det_output/1.0"


class DetError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_det_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path else DEFAULT_DET_CONFIG
    with open(config_path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_markets_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path else DEFAULT_MARKETS_CONFIG
    with open(config_path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def compute_sufficiency(
    factors: dict[str, Any], critical_factors: list[str]
) -> str:
    """P20 §3.5: c = available/total; critical set config-pinned per scope."""
    total = len(factors)
    available = sum(1 for factor in factors.values() if factor.get("available"))
    coverage = available / total if total else 0.0
    critical_missing = [
        name for name in critical_factors if not factors.get(name, {}).get("available")
    ]
    if coverage < 0.7 or len(critical_missing) >= 2:
        return "INSUFFICIENT"
    if coverage >= 0.9 and not critical_missing:
        return "SUFFICIENT"
    return "SPARSE"


def _team_values(factor: dict[str, Any], key: str) -> set[str]:
    return {
        str(row.get(key))
        for row in factor.get("rows", [])
        if row.get(key) not in (None, "")
    }


def _evaluate_check(
    check: dict[str, Any], factors: dict[str, Any], away: str, home: str
) -> tuple[str, str]:
    factor_name = check.get("factor")
    rule = check.get("rule")
    factor = factors.get(factor_name)
    if factor is None:
        return "FAIL", f"factor '{factor_name}' absent from framing object"

    if rule == "factor_available":
        if factor.get("available"):
            return "PASS", f"{factor_name} available"
        return "FAIL", f"{factor_name} unavailable"

    if rule == "both_teams_present":
        if not factor.get("available"):
            return "NOT_EVALUABLE", f"{factor_name} unavailable"
        present = _team_values(factor, "team") | _team_values(factor, "selection")
        missing = [team for team in (away, home) if team not in present]
        if missing:
            return "FAIL", f"{factor_name} missing side(s): {missing}"
        return "PASS", f"{factor_name} covers both sides"

    if rule == "lineups_complete":
        if not factor.get("available"):
            return "NOT_EVALUABLE", f"{factor_name} unavailable"
        per_team = int(check.get("params", {}).get("per_team", 9))
        counts: dict[str, int] = {}
        for row in factor.get("rows", []):
            team = row.get("team")
            counts[team] = counts.get(team, 0) + 1
        short = [team for team in (away, home) if counts.get(team, 0) < per_team]
        if short:
            return "FAIL", f"{factor_name} incomplete for: {short}"
        return "PASS", f"{factor_name} has >= {per_team} batters per side"

    return "NOT_EVALUABLE", f"unknown rule '{rule}'"


def run_det(
    framing_object: dict[str, Any],
    *,
    det_config: dict[str, Any] | None = None,
    markets_config: dict[str, Any] | None = None,
    run_id: str | None = None,
    out_root: str | Path | None = None,
) -> dict[str, Any]:
    """Produce a `det_output/1.0` for one framing object (facts about data only)."""
    det = det_config or load_det_config()
    markets = markets_config or load_markets_config()
    scope_name = framing_object["market_scope"]
    try:
        critical = markets["scopes"][scope_name]["sufficiency_critical_factors"]
    except KeyError as exc:
        raise DetError(f"unregistered market_scope: {scope_name}") from exc

    away, home = split_game_key(framing_object["game_key"])
    factors = framing_object["factors"]

    checks: list[dict[str, str]] = []
    for check in det.get("checks", []):
        result, detail = _evaluate_check(check, factors, away, home)
        checks.append(
            {"check_id": check["check_id"], "result": result, "detail": detail}
        )

    run = run_id or framing_object["run_id"]
    payload: dict[str, Any] = {
        "schema_id": DET_SCHEMA,
        "run_id": run,
        "produced_at": _utc_now(),
        "provenance": {
            "stage": "DET",
            "persona": None,
            "model_id": None,
            "input_artifact_hashes": [sha256_json(framing_object)],
        },
        "game_key": framing_object["game_key"],
        "market_scope": scope_name,
        "det_checks_version": det["det_checks_version"],
        "checks": checks,
        "data_sufficiency": compute_sufficiency(factors, critical),
    }
    validate(payload, DET_SCHEMA)

    if out_root is not None:
        run_dir = Path(out_root) / run / "det"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / f"{slugify(payload['game_key'])}.json").write_text(
            json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8"
        )
    return payload


def run_det_slate(
    framing_objects: list[dict[str, Any]],
    *,
    det_config: dict[str, Any] | None = None,
    markets_config: dict[str, Any] | None = None,
    run_id: str | None = None,
    out_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    det = det_config or load_det_config()
    markets = markets_config or load_markets_config()
    return [
        run_det(
            obj,
            det_config=det,
            markets_config=markets,
            run_id=run_id,
            out_root=out_root,
        )
        for obj in framing_objects
    ]
