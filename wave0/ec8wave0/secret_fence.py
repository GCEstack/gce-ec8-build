"""SecretFence — SE-5 Wave 0 half (spec §4.5).

Wave 0 makes no API call. The process may READ the environment to prove fencing, but must
NEVER persist env secret values into store bytes, backup bytes, logs, or evidence files.

This module provides scan helpers that report COUNTS ONLY. Callers never receive or echo
the secret values themselves. Scan functions are byte-level so they operate equally on
store payloads, backup blobs, log files, and whole directories.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Iterable


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except Exception:
        return b""


def scan_bytes(data: bytes, secret: bytes) -> int:
    """Count occurrences of `secret` (as bytes) inside `data`. Count only — value not returned."""
    if not secret:
        return 0
    return data.count(secret)


def scan_file(path: Path, secret: bytes) -> int:
    """Count occurrences of `secret` inside one file. Returns count only."""
    return scan_bytes(_read_bytes(path), secret)


def scan_path(path: Path, secret: bytes) -> int:
    """Count occurrences of `secret` under a file or directory tree (recursive)."""
    if path.is_file():
        return scan_file(path, secret)
    total = 0
    if path.is_dir():
        for p in path.rglob("*"):
            if p.is_file():
                total += scan_file(p, secret)
    return total


def env_secret_values(names: Iterable[str]) -> list[str]:
    """Return present env values for the given secret variable names (used to build scan set)."""
    return [os.environ[n] for n in names if os.environ.get(n)]


def count_only_report(
    label: str,
    hits: int,
    destinations: list[str],
) -> str:
    """Produce a counts-only line for evidence. Never includes a secret value."""
    return f"{label}={hits} destinations=({', '.join(destinations) or 'none'})"
