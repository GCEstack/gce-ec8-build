"""WS5 — binding verification primitives (P20 §1.1, §1.2 steps 2–4).

Pure functions: manifest parsing/canonicalization, per-member SHA-256
verification, and the composite digest. Counts are always derived here, at
runtime, from the manifest — never hard-coded (P22-7 / locked control L9).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .models import (
    REASON_HASH_MISMATCH,
    REASON_MALFORMED_MANIFEST,
    BindingRejected,
    ManifestEntry,
)

# "<64 hex>  <relpath>" (two spaces per the manifest, tolerate any run of whitespace).
_MANIFEST_LINE_RE = re.compile(r"^([0-9A-Fa-f]{64})[ \t]+(.+?)[ \t]*$")

_CHUNK = 1024 * 1024


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def canonical_relpath(relpath: str) -> str:
    return relpath.strip().replace("\\", "/")


def parse_manifest(text: str) -> list[ManifestEntry]:
    """Parse the hash manifest into canonicalized, relpath-sorted entries.

    Canonicalization (P20 §1.2 step 2): uppercase hex digests, forward-slash
    relpaths, sorted by relpath. Any unparseable non-empty line is fatal.
    """
    entries: list[ManifestEntry] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        match = _MANIFEST_LINE_RE.match(line)
        if not match:
            raise BindingRejected(
                REASON_MALFORMED_MANIFEST,
                path=f"line {lineno}",
                detail=f"unparseable manifest line: {line!r}",
            )
        digest, relpath = match.group(1).upper(), canonical_relpath(match.group(2))
        entries.append(ManifestEntry(relpath=relpath, sha256=digest))
    if not entries:
        raise BindingRejected(
            REASON_MALFORMED_MANIFEST, detail="manifest contains no entries"
        )
    entries.sort(key=lambda e: e.relpath)
    return entries


def canonical_manifest_bytes(entries: list[ManifestEntry]) -> bytes:
    """Canonical manifest content: `"<sha256>  <relpath>\\n"` over sorted relpaths."""
    return "".join(f"{e.sha256}  {e.relpath}\n" for e in entries).encode("utf-8")


def composite_digest(entries: list[ManifestEntry]) -> str:
    """SHA-256 of the canonicalized manifest content (P20 §1.2 step 4)."""
    return sha256_bytes(canonical_manifest_bytes(entries))


def manifest_counts(entries: list[ManifestEntry]) -> tuple[int, int]:
    """Runtime-derived (entry_count, distinct_digest_count). Never hard-coded."""
    return len(entries), len({e.sha256 for e in entries})


def verify_members(root: str | Path, entries: list[ManifestEntry]) -> None:
    """Recompute SHA-256 of every listed file. Hard stop on any failure.

    Per P20 §1.2 step 3: a missing listed file or a digest mismatch is a
    HASH_MISMATCH (the four required binding artifacts are guarded separately as
    MISSING_ARTIFACT when they cannot be read).
    """
    root = Path(root)
    for entry in entries:
        path = root / entry.relpath
        if not path.is_file():
            raise BindingRejected(
                REASON_HASH_MISMATCH,
                path=entry.relpath,
                detail="listed file is missing from the freeze tree",
            )
        actual = sha256_file(path)
        if actual.upper() != entry.sha256:
            raise BindingRejected(
                REASON_HASH_MISMATCH,
                path=entry.relpath,
                detail=f"expected {entry.sha256}, recomputed {actual.upper()}",
            )
