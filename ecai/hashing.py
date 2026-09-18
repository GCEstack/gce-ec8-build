"""Deterministic content hashing for ECAI artifacts.

Canonical JSON (sorted keys, compact separators, ASCII) so a stage can hash a
consumed artifact into its `provenance.input_artifact_hashes` reproducibly.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json_bytes(obj: Any) -> bytes:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def sha256_json(obj: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(obj)).hexdigest()
