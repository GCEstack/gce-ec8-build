"""Artifact-schema validator, versioning, terminal pointer and seal — AS-1..4 scaffold.

Nine-section structural validator (S1..S9). Header carries `artifact_schema_version` and
`methodology_version`. AS-2 versioning rules: minor = additive fields only; a new enum
value is a major change; consumers declare a supported major and unknown fields within
it are tolerated-and-logged. AS-3 terminal pointer rule is machine-enforced: if the
Pre-Game artifact fails, SAP-Morning is NEVER promoted (a Morning landscape consumed as
terminal would misrepresent evidence vintage). AS-4: sealed at G6 by hash; a post-seal
change requires a new artifact id + reason record.

Structural only. No methodological content is judged here.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

REQUIRED_HEADER = ("artifact_id", "artifact_schema_version", "methodology_version", "run_id", "generated_at")
SECTIONS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9")
S3_REQUIRED = ("configured_n", "ran_n", "included_n", "excluded_n", "exclusions", "retry_count", "crash_restart_count")


def build_artifact_id(slate_id: str, run_type: str, ts: str) -> str:
    return f"SAP-{slate_id}-{run_type}-{ts}"


def _missing(required: tuple[str, ...], got: dict[str, Any]) -> list[str]:
    return [k for k in required if k not in got]


def structural_validate(artifact: dict[str, Any]) -> list[str]:
    """Return a list of structural violations; empty list == structurally conforming."""
    violations: list[str] = []
    header = artifact.get("header")
    if not isinstance(header, dict):
        return ["header missing"]
    violations += [f"header.{k} missing" for k in _missing(REQUIRED_HEADER, header)]
    for sec in SECTIONS:
        if sec not in artifact:
            violations.append(f"section {sec} missing")
    if "S3" in artifact and isinstance(artifact["S3"], dict):
        violations += [f"S3.{k} missing" for k in _missing(S3_REQUIRED, artifact["S3"])]
    return violations


def schema_major(ver: str) -> int:
    return int(ver.split(".")[0])


def schema_minor(ver: str) -> int:
    return int(ver.split(".")[1]) if "." in ver else 0


def version_change_kind(current: str, proposed: str, new_enum_introduced: bool) -> dict[str, Any]:
    """AS-2 rule evaluation. Returns kind: 'ok_additive' | 'ok_major' | 'not_allowed'."""
    cur_major, cur_minor = schema_major(current), schema_minor(current)
    new_major, new_minor = schema_major(proposed), schema_minor(proposed)
    if new_major > cur_major:
        return {"kind": "ok_major", "detail": "major bump recorded"}
    if new_major == cur_major and new_enum_introduced:
        return {"kind": "not_allowed", "detail": "new enum value requires a MAJOR version bump (AS-2)"}
    if new_major == cur_major and new_minor >= cur_minor:
        return {"kind": "ok_additive", "detail": "additive minor change"}
    return {"kind": "not_allowed", "detail": "schema version may not decrease"}


def scan_unknown_fields(artifact: dict[str, Any], supported_major: int) -> list[str]:
    """Consumers tolerate-and-log unknown fields within their supported major (never silently)."""
    header = artifact.get("header", {})
    major = schema_major(str(header.get("artifact_schema_version", "0")))
    if major > supported_major:
        return ["artifact schema major not supported by consumer"]
    known = {"header", *SECTIONS}
    return [k for k in artifact if k not in known]


def _artifact_identifier(a: dict[str, Any] | None) -> str | None:
    if not isinstance(a, dict):
        return None
    if a.get("artifact_id"):
        return a["artifact_id"]
    header = a.get("header")
    if isinstance(header, dict) and header.get("artifact_id"):
        return header["artifact_id"]
    return None


def resolve_terminal(
    slate_id: str,
    pregame: dict[str, Any] | None,
    morning: dict[str, Any] | None,
    pregame_failed: bool,
) -> dict[str, Any]:
    """AS-3: scheduled terminal = SAP-PreGame on G6 pass; Morning is never promoted on a
    Pre-Game failure. Returns a pointer object {slate_id, terminal_artifact_id|null,
    status, reason} — never the run type, and never SAP-Morning on a failed Pre-Game."""
    if pregame is not None and not pregame_failed:
        return {
            "slate_id": slate_id,
            "terminal_artifact_id": _artifact_identifier(pregame),
            "status": "complete",
            "reason": "SAP-PreGame sealed at G6",
        }
    if pregame_failed:
        return {
            "slate_id": slate_id,
            "terminal_artifact_id": None,
            "status": "failed",
            "reason": "SAP-PreGame failed at G6; SAP-Morning NEVER promoted (AS-3)",
        }
    return {"slate_id": slate_id, "terminal_artifact_id": None, "status": "absent", "reason": "no terminal artifact"}


def _canonical(artifact: dict[str, Any]) -> bytes:
    return json.dumps(artifact, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def seal(artifact: dict[str, Any]) -> dict[str, Any]:
    """AS-4: sealed at G6 by SHA-256 of the canonical artifact bytes."""
    digest = hashlib.sha256(_canonical(artifact)).hexdigest()
    return {"sealed": True, "sha256": digest, "artifact_id": artifact.get("header", {}).get("artifact_id")}


def verify_seal(artifact: dict[str, Any], expected_sha256: str) -> bool:
    return hashlib.sha256(_canonical(artifact)).hexdigest() == expected_sha256


def reseal_after_change(artifact: dict[str, Any], reason: str) -> dict[str, Any]:
    """A post-seal content change is a NEW artifact id + reason record (AS-4)."""
    changed = json.loads(_canonical(artifact).decode("utf-8"))
    old_id = artifact.get("header", {}).get("artifact_id", "unknown")
    new_id = old_id + ".R"
    changed["header"] = dict(changed.get("header", {}))
    changed["header"]["artifact_id"] = new_id
    changed["post_seal_reason"] = reason
    return {"artifact": changed, "new_artifact_id": new_id, "reason_recorded": reason}
