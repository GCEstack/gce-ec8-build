"""WS5 — binding adapter data models (P20 §1.2, §2.1).

The adapter is read-only against the freeze; the only write it performs is the
emitted `binding.json` under a caller-supplied runs root.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Rejection taxonomy (P20 §1.2) — terminal states.
REASON_HASH_MISMATCH = "HASH_MISMATCH"
REASON_MISSING_ARTIFACT = "MISSING_ARTIFACT"
REASON_MALFORMED_MANIFEST = "MALFORMED_MANIFEST"
REASON_SLATE_DATE_MISMATCH = "SLATE_DATE_MISMATCH"
REASON_EMPTY_ELIGIBLE_SET = "EMPTY_ELIGIBLE_SET"

REJECTION_REASONS: frozenset[str] = frozenset(
    {
        REASON_HASH_MISMATCH,
        REASON_MISSING_ARTIFACT,
        REASON_MALFORMED_MANIFEST,
        REASON_SLATE_DATE_MISMATCH,
        REASON_EMPTY_ELIGIBLE_SET,
    }
)

BINDING_SCHEMA_VERSION = "ecai/binding_record/1.0"
BINDING_STAGE = "BINDING"

# The four binding reads (P20 §1.2 step 1). Nothing else is read for binding.
REQUIRED_ARTIFACTS: tuple[str, ...] = (
    "DATASET_BINDING.md",
    "control/DATASET_HASHES_SHA256.txt",
    "governance/ANCHOR_COMMIT_EARLYCLUSTER_2026-09-15.md",
    "governance/EARLY_CLUSTER_READINESS_2026-09-15.csv",
)

MANIFEST_RELPATH = "control/DATASET_HASHES_SHA256.txt"


class BindingRejected(Exception):
    """Terminal rejection: hard stop, no partial binding (P20 §1.2)."""

    def __init__(self, reason: str, path: str | None = None, detail: str | None = None):
        if reason not in REJECTION_REASONS:
            raise ValueError(f"unknown rejection reason: {reason}")
        self.reason = reason
        self.path = path
        self.detail = detail
        message = reason
        if path is not None:
            message += f" ({path})"
        if detail is not None:
            message += f": {detail}"
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": "rejected", "reason": self.reason}
        if self.path is not None:
            out["path"] = self.path
        if self.detail is not None:
            out["detail"] = self.detail
        return out


@dataclass(frozen=True)
class ManifestEntry:
    """A canonicalized `(relpath, sha256)` pair from the hash manifest."""

    relpath: str
    sha256: str  # uppercase hex, forward-slash relpath (P20 §1.2 step 2)


@dataclass
class BindingRecord:
    """The emitted `ecai/binding_record/1.0` artifact."""

    run_id: str
    produced_at: str
    dataset_id: str
    freeze_timestamp: str
    slate_date: str
    game_count: int
    join_key_format: str
    composite_digest: str
    manifest_path: str
    manifest_entry_count: int
    manifest_distinct_digests: int
    eligible_games: list[str]
    per_game: dict[str, str]
    excluded_matchups: list[dict[str, str]]
    source_artifacts: list[dict[str, str]]
    prose_discrepancies: list[dict[str, Any]] = field(default_factory=list)
    input_artifact_hashes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_id": BINDING_SCHEMA_VERSION,
            "run_id": self.run_id,
            "produced_at": self.produced_at,
            "provenance": {
                "stage": BINDING_STAGE,
                "persona": None,
                "model_id": None,
                "input_artifact_hashes": list(self.input_artifact_hashes),
            },
            "dataset_id": self.dataset_id,
            "freeze_timestamp": self.freeze_timestamp,
            "slate": {
                "date": self.slate_date,
                "game_count": self.game_count,
                "join_key_format": self.join_key_format,
            },
            "composite_digest": self.composite_digest,
            "manifest_path": self.manifest_path,
            "manifest_entry_count": self.manifest_entry_count,
            "manifest_distinct_digests": self.manifest_distinct_digests,
            "gate_status": {
                "eligible_games": list(self.eligible_games),
                "per_game": dict(self.per_game),
            },
            "excluded_matchups": list(self.excluded_matchups),
            "source_artifacts": list(self.source_artifacts),
            "binding_schema_version": BINDING_SCHEMA_VERSION,
            "prose_discrepancies": list(self.prose_discrepancies),
        }
