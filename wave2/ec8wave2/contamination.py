"""Contamination mechanisms — CD-1..4 scaffold.

CD-1 canary injection: per analyst per run, >=3 collision-resistant inert canaries from
a >=2^64 space on >=3 injection surfaces; post-run cross-scan flags any canary appearing
in a non-owner output (contamination event -> integrity report / escalation), and canary
values are stripped from the artifact (instrumentation, not content).
CD-2 fingerprinting: deterministic lexical features; a threshold breach is an
INVESTIGATION flag, never an auto-exclusion (false-positive guard).
CD-3 pairwise sampling: post-hoc random pairs; rate/cadence is Talon's to set.
CD-4 continuity verification is delegated to the session machine-check hook.
"""

from __future__ import annotations

import hashlib
import random
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from ._stubs import canary_token
from .session import SessionRecord, verify_session_continuity

CANARY_SURFACES = ("system_prompt", "framing_delivery", "evidence_package_envelope")
CANARY_RE = re.compile(r"EC8C_[0-9a-f]{32}")


@dataclass
class CanaryProgram:
    """Injects canaries and cross-scans outputs (CD-1)."""

    run_id: str
    _owners: dict[str, list[str]] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    def inject(self, analyst: str, surfaces: tuple[str, ...] = CANARY_SURFACES) -> list[str]:
        tokens = [canary_token() for _ in surfaces]
        self._owners[analyst] = tokens
        return tokens

    def owners(self) -> dict[str, list[str]]:
        return {k: list(v) for k, v in self._owners.items()}

    def cross_scan(self, outputs: dict[str, list[str]]) -> list[dict[str, Any]]:
        for analyst, tokens in self._owners.items():
            for tok in tokens:
                for other, texts in outputs.items():
                    if other == analyst:
                        continue
                    joined = "\n".join(texts)
                    if tok in joined:
                        self.events.append(
                            {
                                "run_id": self.run_id,
                                "canary": tok,
                                "owner": analyst,
                                "found_in": other,
                                "kind": "contamination",
                                "escalation": "G1/G6 integrity",
                            }
                        )
        return list(self.events)

    @staticmethod
    def strip(text: str) -> str:
        return CANARY_RE.sub("<canary-stripped>", text)


class Fingerprinter:
    """Deterministic lexical fingerprinting (CD-2). Breach = investigation flag only."""

    def __init__(self, threshold: float = 0.85):
        self.threshold = threshold

    @staticmethod
    def features(text: str) -> frozenset[str]:
        toks = re.findall(r"[a-z0-9]+", text.lower())
        features = set()
        for a, b in zip(toks, toks[1:]):
            features.add("bigram:" + a + "|" + b)
        for trig in re.findall(r"[a-z0-9#%]{3}", text.lower()):
            features.add("trigram:" + trig)
        return frozenset(features)

    @classmethod
    def similarity(cls, a: str, b: str) -> float:
        fa, fb = cls.features(a), cls.features(b)
        if not fa and not fb:
            return 1.0
        inter = len(fa & fb)
        union = len(fa | fb)
        return inter / union if union else 0.0

    def check(self, texts: dict[str, str]) -> list[dict[str, Any]]:
        """Reports pairs above threshold as INVESTIGATION flags; never auto-exclusion."""
        flags: list[dict[str, Any]] = []
        names = list(texts)
        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                sim = self.similarity(texts[a], texts[b])
                if sim >= self.threshold:
                    flags.append({"pair": [a, b], "similarity": round(sim, 3), "action": "investigate", "auto_exclusion": False})
        return flags


class PairwiseSampler:
    """Post-hoc random pair selection (CD-3). Cadence/rate is Talon-owned configuration."""

    def select(self, analysts: list[str], rng: random.Random | None = None, k: int | None = None) -> list[tuple[str, str]]:
        rng = rng or random.Random()
        if k is None:
            k = max(1, len(analysts) // 2)
        shuffled = list(analysts)
        rng.shuffle(shuffled)
        return [(shuffled[i], shuffled[i + 1]) for i in range(0, len(shuffled) - 1, 2)][:k]


def continuity_flags(records: list[SessionRecord]) -> list[dict[str, Any]]:
    return verify_session_continuity(records)
