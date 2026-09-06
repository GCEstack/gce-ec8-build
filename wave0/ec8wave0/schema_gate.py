"""SchemaGate — validation gate enforced BEFORE any commit (spec §4.5 / §4.1).

Guarantees:
  * all nine required fields present (identity + provenance + content);
  * `run_type` ∈ {Overnight, Morning, PreGame} — rejects `OnDemand` and any other value;
  * snapshot/acquire/expire timestamps are timezone-aware.
`reliability_tier` is a NON-EMPTY string only (closed enum is a STOP/ROUTE item — not
encoded here; fixture strings are data, not law). `data_class` if present is preserved
verbatim and never policed (data_class taxonomy is a STOP/ROUTE item — see spec §5).
"""

from __future__ import annotations

import re
from typing import Any

VALID_RUN_TYPES: frozenset[str] = frozenset({"Overnight", "Morning", "PreGame"})

REQUIRED_FIELD_NAMES: tuple[str, ...] = (
    "entity",
    "attribute",
    "snapshot_time",
    "acquired_at",
    "source",
    "reliability_tier",
    "run_type",
    "expires_at",
    "content",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_INCOMPLETE = "incomplete_provenance"
_INVALID_RUN_TYPE = "invalid_run_type"
_HASH_MISMATCH = "hash_mismatch"
_DUPLICATE_IDENTITY = "duplicate_identity"


def validate_required_fields(item: dict[str, Any]) -> str | None:
    """Absence (missing key or None) of any required field → incomplete_provenance.

    Presence is tested by KEY EXISTENCE, not value truthiness, so a PRESENT-but-invalid
    `run_type` (e.g. ``""`` or ``OnDemand``) is NOT classified incomplete here — it is
    routed to `invalid_run_type` by `validate_run_type`. Only an absent/None field is
    incomplete (spec §4.6: run_type "missing" vs "other value" are distinct rejections).
    """
    for field in REQUIRED_FIELD_NAMES:
        if field not in item or item[field] is None:
            return _INCOMPLETE
        if field in ("entity", "attribute", "source", "reliability_tier"):
            if not isinstance(item[field], str) or not item[field].strip():
                return _INCOMPLETE
    return None


def validate_run_type(item: dict[str, Any]) -> str | None:
    """A present run_type whose value is not in the enum → invalid_run_type.

    Absent run_type is caught as incomplete_provenance by validate_required_fields (the
    ordering guarantees a present-but-invalid value is never masked as incomplete).
    """
    if "run_type" not in item or item["run_type"] is None:
        return None  # absence handled by completeness gate
    rt = item["run_type"]
    if rt not in VALID_RUN_TYPES:
        return _INVALID_RUN_TYPE
    return None


def validate_timestamps_aware(item: dict[str, Any]) -> str | None:
    """Timestamp fields must be timezone-aware (datetime with tzinfo, or tz'd ISO string)."""
    for field in ("snapshot_time", "acquired_at", "expires_at"):
        value = item.get(field)
        if value is None:
            return _INCOMPLETE
        from datetime import datetime

        if isinstance(value, datetime):
            if value.tzinfo is None:
                return _INCOMPLETE
        elif isinstance(value, str):
            if "Z" not in value and "+" not in value:
                return _INCOMPLETE
        else:
            return _INCOMPLETE
    return None


def validate_content_sha256_format(content_sha256: str) -> bool:
    """Structural check: 64 lowercase hex chars."""
    return bool(_SHA256_RE.match(content_sha256 or ""))
