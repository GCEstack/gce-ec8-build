"""Canonical deterministic serializer for EC8 Wave 0 evidence items.

Hash input contract (spec §4.2, "Hash input"): canonical serialization of all required
fields EXCEPT `content_sha256` (and except `evidence_id`, which this store treats as an
optional synonym of the hash and therefore excludes). The algorithm below is the single
source of truth used for BOTH write and verify.

Canonical form rules (documented; deterministic):
  * Only the nine required fields participate in the hash payload:
        entity, attribute, snapshot_time, acquired_at, source,
        reliability_tier, run_type, expires_at, content
  * `content_sha256` and `evidence_id` are excluded from the payload.
  * Timestamps are normalized to UTC and rendered as RFC 3339 (e.g.
    ``2026-09-06T00:00:00Z``) with microseconds preserved when nonzero.
  * `content` is canonicalized: JSON values are serialized with keys sorted and the
    RFC 8259 minimal separators (`,:`); raw bytes are base64-encoded under a marker so
    that the encoding is reversible and deterministic.
  * Keys are emitted in the fixed order above (not dict insertion order), so the same
    logical item always yields identical bytes regardless of the caller's key order.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

# Fixed, documented field order for the hash payload.
REQUIRED_FIELDS: tuple[str, ...] = (
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

# Fields that are allowed on an item but never hashed.
EXCLUDED_FROM_HASH: tuple[str, ...] = ("content_sha256", "evidence_id")

_BYTES_MARKER = "__ec8_bytes_b64__"


def _to_utc(value: Any) -> datetime:
    """Normalize a timezone-aware datetime (or ISO-8601 str) to aware UTC."""
    if isinstance(value, str):
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    elif isinstance(value, datetime):
        dt = value
    else:
        raise TypeError(f"timestamp field must be datetime or ISO-8601 str, got {type(value)!r}")
    if dt.tzinfo is None:
        raise ValueError(f"timestamp field must be timezone-aware, got naive: {dt!r}")
    return dt.astimezone(timezone.utc)


def format_timestamp(value: Any) -> str:
    """RFC 3339 UTC canonical rendering used everywhere in serialized records."""
    dt = _to_utc(value)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    micro = dt.strftime(".%f").rstrip("0").rstrip(".")
    return f"{base}{micro}Z"


def _canonical_content(content: Any) -> str:
    """Deterministic, reversible canonical text for the `content` field."""
    if isinstance(content, bytes):
        return json.dumps(
            {_BYTES_MARKER: base64.b64encode(content).decode("ascii")},
            sort_keys=True,
            separators=(",", ":"),
        )
    # JSON value: sorted keys, minimal separators, no extra whitespace.
    return json.dumps(content, sort_keys=True, separators=(",", ":"))


def _build_payload_dict(item: dict[str, Any]) -> dict[str, Any]:
    """Return only the nine required fields in canonical (text) form, in fixed order."""
    missing = [f for f in REQUIRED_FIELDS if f not in item]
    if missing:
        raise ValueError(f"missing required field(s): {', '.join(missing)}")
    payload: dict[str, Any] = {}
    for field in REQUIRED_FIELDS:
        value = item[field]
        if field in ("snapshot_time", "acquired_at", "expires_at"):
            payload[field] = format_timestamp(value)
        elif field == "content":
            payload[field] = _canonical_content(value)
        else:
            payload[field] = value
    return payload


def canonical_payload_bytes(item: dict[str, Any]) -> bytes:
    """Canonical bytes of the hash payload for an item (required fields only)."""
    payload = _build_payload_dict(item)
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=False,  # keys already in fixed REQUIRED_FIELDS order
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_hex(item: dict[str, Any]) -> str:
    """Lowercase 64-hex SHA-256 over the canonical payload (content_sha256 excluded)."""
    return hashlib.sha256(canonical_payload_bytes(item)).hexdigest()
