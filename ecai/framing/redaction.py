"""WS5 framing — source-only redaction rules (P20 §2.2, T-01 / T-14).

The framer is a *transcoder*, not an analyst. This module is the enforcement
point for:
  * the factor whitelist (no keys outside it ever reach a framing object);
  * the BetMGM-only provenance constraint (no other book, no consensus, no Kalshi);
  * the exclusion of derived stats / DET output / grades / prior picks / bankroll.

Locked controls guarded here: L1 (BetMGM-source-only reasoning inputs) and
L2 (consensus/Kalshi excluded from the reasoning path).
"""

from __future__ import annotations

from typing import Any, Iterable

# P20 §2.2 factor whitelist — the only reasoning inputs a framing object may carry.
FACTOR_WHITELIST: tuple[str, ...] = (
    "pitchers",
    "bullpen",
    "lineups",
    "umpire",
    "weather",
    "rest",
    "injuries",
    "team_evidence",
    "odds_betmgm",
)

# Source-file name tokens that must never be read into the reasoning path (P22-3).
FORBIDDEN_SOURCE_TOKENS: tuple[str, ...] = ("consensus", "kalshi")

# Top-level framing keys that would indicate an analyst output leaked into framing.
FORBIDDEN_FRAMING_KEYS: tuple[str, ...] = (
    "pick",
    "score",
    "confidence",
    "confidence_hint",
    "grade",
    "bankroll",
    "stake",
    "recommendation",
    "det_output",
    "det_checks",
    "verdict",
    "lean",
)


class RedactionViolation(ValueError):
    """Raised when a framing object would carry a non-source-only input."""


def is_forbidden_source(relpath: str) -> bool:
    lowered = str(relpath).lower().replace("\\", "/")
    return any(token in lowered for token in FORBIDDEN_SOURCE_TOKENS)


def assert_source_allowed(relpath: str) -> None:
    if is_forbidden_source(relpath):
        raise RedactionViolation(
            f"forbidden source in reasoning path (consensus/Kalshi): {relpath}"
        )


def assert_factor_keys(factors: dict[str, Any]) -> None:
    extra = set(factors) - set(FACTOR_WHITELIST)
    missing = set(FACTOR_WHITELIST) - set(factors)
    if extra:
        raise RedactionViolation(f"factor keys outside whitelist: {sorted(extra)}")
    if missing:
        raise RedactionViolation(f"factor keys missing from whitelist: {sorted(missing)}")


def assert_framing_redacted(payload: dict[str, Any]) -> None:
    """No analyst/derived field may appear at the framing object's top level."""
    leaked = set(payload) & set(FORBIDDEN_FRAMING_KEYS)
    if leaked:
        raise RedactionViolation(f"non-source-only keys in framing object: {sorted(leaked)}")


def project_columns(row: dict[str, Any], columns: Iterable[str]) -> dict[str, Any]:
    """Keep only whitelisted raw columns (pass-through; no transformation)."""
    return {key: row[key] for key in columns if key in row}
