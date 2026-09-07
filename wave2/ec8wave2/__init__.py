"""ec8wave2 — Wave 2 Isolation & Wiring scaffold slice (BRIEF-20260906-EC8-W2).

Scaffolds yes, semantics no. Every module here binds to a Chiave/A0 contract listed
in the brief §2 in-scope. Any surface whose meaning is not yet closed (FC enum values,
Pass override, Contradicted, gap/status enums, CH bounds, canary-in-package policy,
ran_n-on-retry, exclusion-record shape, market policy, L3 live execution) is either
absent or represented as a FAIL-CLOSED placeholder that raises on use. Nothing here
encodes a semantic default.

Reads (never modifies) the Wave 1 package ec8wave1 for the provider abstraction,
execution-point ledger and emitter — the no-retrofit meter contract (OB-3) continues
into Wave 2 wiring at the execution point.
"""

from __future__ import annotations

import sys
from pathlib import Path

_BUILD_ROOT = Path(__file__).resolve().parents[2]
_WAVE1 = _BUILD_ROOT / "wave1"
if str(_WAVE1) not in sys.path:
    sys.path.insert(0, str(_WAVE1))

WAVE2_ROOT = Path(__file__).resolve().parents[1]
WAVE2_PACKAGE = "ec8wave2"
WAVE2_BRIEF = "BRIEF-20260906-EC8-W2"
