"""WS4 — runtime manifest + quorum policy (P20 §5.1, §3.4).

The manifest is the single explicit surface for model substitution: the runtime
refuses any model id not declared here. MODEL != ROLE != SEAT.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..hashing import sha256_json

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
DEFAULT_MANIFEST = CONFIG_DIR / "roles.bedrock.yaml"

QUORUM_STOP = "STOP_BELOW_QUORUM"
QUORUM_OK = "OK"


class ManifestError(RuntimeError):
    pass


class UndeclaredModelError(ManifestError):
    """Raised when a model id is used that is not declared in the manifest."""


@dataclass(frozen=True)
class Occupant:
    model_id: str
    family: str
    personas: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuntimeManifest:
    manifest_version: str
    region: str
    analysts: tuple[Occupant, ...]
    gatekeeper: Occupant
    timeout_s: int
    max_retries: int
    backoff_s: tuple[int, ...]
    parse_retries: int
    quorum_fraction: float
    quorum_floor: int
    quorum_window_s: int
    raw: dict[str, Any] = field(default_factory=dict)

    # ---------- identity / hashing ----------
    def manifest_hash(self) -> str:
        return sha256_json(self.raw)

    def declared_model_ids(self) -> set[str]:
        ids = {o.model_id for o in self.analysts}
        ids.add(self.gatekeeper.model_id)
        return ids

    def families(self) -> set[str]:
        return {o.family for o in self.analysts} | {self.gatekeeper.family}

    def occupant_for_persona(self, persona: str) -> Occupant | None:
        for occupant in self.analysts:
            if persona in occupant.personas:
                return occupant
        return None

    def active_roster(self) -> tuple[str, ...]:
        return tuple(p for o in self.analysts for p in o.personas)

    def assert_declared(self, model_id: str) -> None:
        if model_id not in self.declared_model_ids():
            raise UndeclaredModelError(
                f"model id not declared in manifest (no silent substitution): {model_id}"
            )


def load_manifest(path: str | Path | None = None) -> RuntimeManifest:
    manifest_path = Path(path) if path else DEFAULT_MANIFEST
    with open(manifest_path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    try:
        analysts = tuple(
            Occupant(
                model_id=entry["model_id"],
                family=entry["family"],
                personas=tuple(entry.get("personas", ())),
            )
            for entry in raw["roles"]["analyst"]["occupants"]
        )
        gk_entry = raw["roles"]["gatekeeper"]["occupant"]
        gatekeeper = Occupant(
            model_id=gk_entry["model_id"], family=gk_entry["family"]
        )
        invocation = raw["invocation"]
        quorum = raw["quorum"]
        manifest = RuntimeManifest(
            manifest_version=raw["manifest_version"],
            region=raw["region"],
            analysts=analysts,
            gatekeeper=gatekeeper,
            timeout_s=int(invocation["timeout_s"]),
            max_retries=int(invocation["max_retries"]),
            backoff_s=tuple(int(b) for b in invocation["backoff_s"]),
            parse_retries=int(invocation["parse_retries"]),
            quorum_fraction=float(quorum["fraction"]),
            quorum_floor=int(quorum["absolute_floor"]),
            quorum_window_s=int(quorum["window_s"]),
            raw=raw,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ManifestError(f"malformed runtime manifest: {exc}") from exc

    if not analysts:
        raise ManifestError("manifest declares no analyst occupants")
    return manifest


# --------------------------------------------------------------------------- quorum
def quorum_requirement(
    active_roster_size: int, fraction: float, absolute_floor: int
) -> int:
    """`max(floor, ceil(fraction x active_roster))` — P20 §3.4, encoded exactly."""
    return max(absolute_floor, math.ceil(fraction * active_roster_size))


def evaluate_quorum(
    valid_analysts: int,
    active_roster_size: int,
    *,
    fraction: float,
    absolute_floor: int,
) -> bool:
    return valid_analysts >= quorum_requirement(
        active_roster_size, fraction, absolute_floor
    )


def quorum_decision(
    valid_analysts: int, manifest: RuntimeManifest
) -> dict[str, Any]:
    """Quorum decision + the convergence stop status when not met (T-05 path)."""
    roster = len(manifest.active_roster())
    requirement = quorum_requirement(
        roster, manifest.quorum_fraction, manifest.quorum_floor
    )
    met = valid_analysts >= requirement
    return {
        "active_roster": roster,
        "requirement": requirement,
        "valid_analysts": valid_analysts,
        "quorum_met": met,
        "status": QUORUM_OK if met else QUORUM_STOP,
    }


# --------------------------------------------------------------------------- substitution
def diff_substitutions(
    previous: RuntimeManifest, current: RuntimeManifest
) -> list[dict[str, Any]]:
    """Explicit, versioned substitutions: only manifest edits change a model id."""
    records: list[dict[str, Any]] = []

    prev_by_persona = {
        persona: occupant
        for occupant in previous.analysts
        for persona in occupant.personas
    }
    for occupant in current.analysts:
        for persona in occupant.personas:
            prior = prev_by_persona.get(persona)
            if prior and prior.model_id != occupant.model_id:
                records.append(
                    {
                        "role": "analyst",
                        "persona": persona,
                        "model_id": occupant.model_id,
                        "substituted_for": prior.model_id,
                        "reason": "manifest_change",
                    }
                )
    if previous.gatekeeper.model_id != current.gatekeeper.model_id:
        records.append(
            {
                "role": "gatekeeper",
                "persona": None,
                "model_id": current.gatekeeper.model_id,
                "substituted_for": previous.gatekeeper.model_id,
                "reason": "manifest_change",
            }
        )
    return records
