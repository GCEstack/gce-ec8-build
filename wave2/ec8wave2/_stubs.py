"""Fail-closed stubbing and structural constants shared across the Wave 2 scaffold.

Rule (brief §4): stub means a fail-closed placeholder that RAISES on use — never a
silent default meaning. Semantic surfaces held by Kimi/Chiave are represented by
`unpinned()` calls or by rejection in the adapters, not by fabricated values.
"""

from __future__ import annotations

import secrets

GATES = ("G0", "G1", "G2", "G3", "G4", "G5", "G6")

ANALYST_LAYERS = ("L1", "L2", "L3")
VALIDATION_STATES = ("pending", "passed", "failed")
VALIDATION_LAYERS = ("L1", "L2", "L3")


class UnpinnedSemanticError(RuntimeError):
    """Raised when an unpinned semantic value would otherwise be used as a default."""


def unpinned(surface: str, owner: str) -> None:
    """Fail-closed marker for a held semantic surface. Never returns normally."""
    raise UnpinnedSemanticError(
        f"unpinned semantic surface '{surface}' is held by {owner}; no default may be encoded (fail closed)"
    )


def canary_token() -> str:
    """Collision-resistant inert token from a >=2^64 space (CD-1). Instrumentation only."""
    return "EC8C_" + secrets.token_hex(16)
