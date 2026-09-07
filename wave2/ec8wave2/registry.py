"""Registry interfaces — PR-1/PR-2 (provider taxonomy) and RG-1..4 (registries) scaffold.

Contract shapes come from Chiave v1.1 §A4/A5. Interfaces + storage only; CONTENT is
fixture/stub (provider/model selection is OUTSIDE this brief — RQ-14 stays unsatisfied;
entity/source/bounds content authority belongs to Luce/Governance/Kimi). The EX-2
pre-flight constraint check is implemented because it is structural (heterogeneity of
families), runs pre-spend, and fails closed at zero cost.

Registries are append-only. A change is a NEW row (retire appends a retired entry);
committed rows are never updated or deleted. RG-4 pinning snapshots the registry version
used at evaluation time for replay auditability.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PR2_FIELDS = ("family_id", "provider_org", "model_id", "version_id", "capability_classes", "status", "pinned_since")
RG1_FIELDS = ("entity_type", "league", "season", "entity_id", "canonical_name", "aliases", "validity_window", "source_of_truth", "version")
RG2_FIELDS = ("source_id", "type", "reliability_tier", "permitted_classes", "market_flag", "status", "governance_ref")
RG3_FIELDS = ("bound_id", "parameter", "operator", "threshold", "scope", "test_id_ref", "methodology_ref", "version")

STATUS_ALLOWED = ("fixture", "pinned", "retired")


def _canonical(entry: dict[str, Any]) -> bytes:
    return json.dumps(entry, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


class Registry:
    """Append-only JSONL registry store (write-once rows, no update/delete of a row)."""

    def __init__(self, path: str | Path, kind: str, required_fields: tuple[str, ...]):
        self.path = Path(path)
        self.kind = kind
        self.required = required_fields
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")

    def _validate(self, entry: dict[str, Any]) -> None:
        missing = [f for f in self.required if f not in entry]
        if missing:
            raise ValueError(f"registry {self.kind} entry missing required fields: {missing}")

    def register(self, entry: dict[str, Any]) -> dict[str, Any]:
        self._validate(entry)
        entry = dict(entry)
        if self.kind == "pr2" and "status" in entry and entry["status"] not in STATUS_ALLOWED:
            raise ValueError(f"unrecognized pr2 status: {entry['status']}")
        row_id = entry.get("row_id") or uuid.uuid4().hex
        full = {
            "row_id": row_id,
            "kind": self.kind,
            "row_sha256": hashlib.sha256(_canonical({**entry, "row_id": row_id})).hexdigest(),
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            **entry,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(full, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n")
        return {"status": "registered", "row_id": row_id}

    def all(self) -> list[dict[str, Any]]:
        out = []
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

    def rows(self) -> list[dict[str, Any]]:
        return self.all()

    def _reset_file(self) -> None:
        self.path.write_text("", encoding="utf-8")


@dataclass
class PreflightResult:
    ok: bool
    violations: list[str]
    checked_before_spend: bool


def pr2_entries_ok(entries: list[dict[str, Any]], roles: dict[str, str]) -> None:
    for e in entries:
        missing = [f for f in PR2_FIELDS if f not in e]
        if missing:
            raise ValueError(f"pr2 entry missing {missing}")


class EX2Preflight:
    """Structural heterogeneity constraint check (EX-2). Runs BEFORE any provider call."""

    def __init__(self, registry: Registry):
        self.registry = registry

    def run(
        self,
        analyst_ids: list[str],
        l2_pairs: list[tuple[str, str]],
        l3_ids: list[str],
        ledger_row_count_at_check: int,
    ) -> PreflightResult:
        violations: list[str] = []
        rows = self.registry.rows()
        by_model: dict[str, dict[str, Any]] = {}
        for r in rows:
            mid = r.get("model_id")
            if mid:
                by_model.setdefault(mid, r)

        def family(model_id: str) -> str:
            if model_id not in by_model:
                return "?"
            return by_model[model_id].get("family_id", "?")

        analyst_families = {family(m) for m in analyst_ids}
        if "?" in analyst_families:
            violations.append("analyst model id(s) not present in provider registry (pre-spend fail-closed)")
        if len(analyst_families - {"?"}) < 3:
            violations.append(f"EX-2 heterogeneity: need >=3 distinct analyst families, got {sorted(analyst_families)}")

        for validator_id, target_id in l2_pairs:
            if validator_id not in by_model or target_id not in by_model:
                violations.append(f"L2 pair references unknown model: {validator_id} -> {target_id}")
                continue
            if family(validator_id) == family(target_id):
                violations.append(f"L2 validator family must differ from target analyst family: {validator_id}({family(validator_id)}) vs {target_id}({family(target_id)})")

        l3_fams = {family(m) for m in l3_ids}
        if "?" in l3_fams:
            violations.append("L3 model id(s) not present in provider registry")
        overlap = analyst_families & l3_fams
        if overlap:
            violations.append(f"L3 must be outside the analyst pool; overlapping families {sorted(overlap)}")

        return PreflightResult(ok=not violations, violations=violations, checked_before_spend=ledger_row_count_at_check == 0)


class RegistryPinner:
    """RG-4: snapshot-hash the registry versions used at evaluation for replay audit."""

    def __init__(self):
        self.pins: dict[str, dict[str, Any]] = {}

    def pin(self, name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        blob = json.dumps(rows, ensure_ascii=True, sort_keys=True).encode("utf-8")
        digest = hashlib.sha256(blob).hexdigest()
        self.pins[name] = {"sha256": digest, "row_count": len(rows)}
        return self.pins[name]
