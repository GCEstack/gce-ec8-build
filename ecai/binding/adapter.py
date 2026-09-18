"""WS5 — binding adapter (P20 §1.2).

`bind(dataset_root)` reads the four binding artifacts only, verifies every
listed file, derives the composite digest and runtime counts, parses the
readiness gate, records prose discrepancies (soft), and emits a
`ecai/binding_record/1.0` artifact. The adapter never writes to the freeze
tree; it writes only the emitted record under a caller-supplied runs root.
"""

from __future__ import annotations

import csv
import io
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..schemas import SchemaValidationError, validate
from . import verify as V
from .models import (
    BINDING_SCHEMA_VERSION,
    MANIFEST_RELPATH,
    REASON_EMPTY_ELIGIBLE_SET,
    REASON_MALFORMED_MANIFEST,
    REASON_MISSING_ARTIFACT,
    REASON_SLATE_DATE_MISMATCH,
    REQUIRED_ARTIFACTS,
    BindingRecord,
    BindingRejected,
)

_DATASET_BINDING_RELPATH = "DATASET_BINDING.md"
_ANCHOR_RELPATH = "governance/ANCHOR_COMMIT_EARLYCLUSTER_2026-09-15.md"
_READINESS_RELPATH = "governance/EARLY_CLUSTER_READINESS_2026-09-15.csv"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_READY_STATUS = "READY_FOR_KIMI"
_JOIN_KEY_FORMAT = "away@home YYYY-MM-DD"


# --------------------------------------------------------------------------- helpers
def _utc_now_rfc3339() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_rfc3339(value: str) -> str | None:
    raw = value.strip().strip("`").strip()
    if not raw:
        return None
    candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _strip_ticks(value: str) -> str:
    return value.strip().strip("`").strip()


def _first_int(value: str) -> int | None:
    match = re.search(r"\d+", value or "")
    return int(match.group(0)) if match else None


def _read_required(root: Path) -> dict[str, str]:
    texts: dict[str, str] = {}
    for relpath in REQUIRED_ARTIFACTS:
        path = root / relpath
        if not path.is_file():
            raise BindingRejected(
                REASON_MISSING_ARTIFACT,
                path=relpath,
                detail="required binding artifact not found",
            )
        texts[relpath] = path.read_text(encoding="utf-8")
    return texts


def _parse_md_table(markdown: str) -> dict[str, str]:
    """Parse simple `| Field | Value |` markdown rows into a mapping."""
    table: dict[str, str] = {}
    for line in markdown.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        key = cells[0]
        if not key or set(key) <= set("-: "):
            continue
        table[key] = "|".join(cells[1:]).strip()
    return table


def _parse_readiness(text: str) -> tuple[list[tuple[str, str]], dict[str, str], list[str], list[dict[str, str]]]:
    reader = csv.DictReader(io.StringIO(text))
    order: list[tuple[str, str]] = []
    per_game: dict[str, str] = {}
    for row in reader:
        game = (row.get("game") or "").strip()
        if not game:
            continue
        status = (row.get("status") or "").strip()
        order.append((game, status))
        per_game[game] = status
    eligible = [game for game, status in order if status == _READY_STATUS]
    excluded = [
        {"game_key": game, "reason": status}
        for game, status in order
        if status != _READY_STATUS
    ]
    return order, per_game, eligible, excluded


def _derive_slate_date(order: list[tuple[str, str]]) -> str:
    for game, _status in order:
        tail = game.split()[-1] if game.split() else ""
        if _DATE_RE.match(tail):
            return tail
    return ""


def _extract_anchor_file_count(markdown: str) -> int | None:
    match = re.search(r"(\d+)\s+files hashed", markdown)
    return int(match.group(1)) if match else None


def _cross_check(
    *,
    root: Path,
    dataset_id: str,
    slate_date: str,
    frozen_prose: int | None,
    excluded_prose: int | None,
    anchor_count: int | None,
    entry_count: int,
    eligible: list[str],
    excluded: list[dict[str, str]],
    per_game: dict[str, str],
) -> list[dict[str, Any]]:
    """Soft cross-checks (P20 §1.2 step 6): record, never silently trust either side."""
    discrepancies: list[dict[str, Any]] = []

    if dataset_id and root.name != dataset_id:
        discrepancies.append(
            {
                "field": "dataset_id",
                "prose_value": dataset_id,
                "authoritative_value": root.name,
                "note": "DATASET_BINDING.md Dataset differs from freeze directory name",
            }
        )
    if frozen_prose is not None and frozen_prose != len(eligible):
        discrepancies.append(
            {
                "field": "slate.frozen_games",
                "prose_value": str(frozen_prose),
                "authoritative_value": str(len(eligible)),
                "note": "DATASET_BINDING.md frozen-games count differs from readiness CSV eligible count",
            }
        )
    if excluded_prose is not None and excluded_prose != len(excluded):
        discrepancies.append(
            {
                "field": "slate.excluded_games",
                "prose_value": str(excluded_prose),
                "authoritative_value": str(len(excluded)),
                "note": "DATASET_BINDING.md excluded-games count differs from readiness CSV non-eligible count",
            }
        )
    if anchor_count is not None and anchor_count != entry_count:
        discrepancies.append(
            {
                "field": "manifest.entry_count",
                "prose_value": str(anchor_count),
                "authoritative_value": str(entry_count),
                "note": "ANCHOR_COMMIT prose 'files hashed' differs from runtime-derived manifest entry count (prose advisory only, P22-7)",
            }
        )
    if slate_date:
        for game in per_game:
            if not game.endswith(slate_date):
                discrepancies.append(
                    {
                        "field": "slate.date",
                        "prose_value": game,
                        "authoritative_value": slate_date,
                        "note": "readiness game key does not carry the binding slate date",
                    }
                )
                break
    return discrepancies


# --------------------------------------------------------------------------- adapter
def bind(
    dataset_root: str | Path,
    *,
    expect_slate: str | None = None,
    run_id: str | None = None,
    out_root: str | Path | None = None,
) -> BindingRecord:
    """Bind the freeze at `dataset_root` and return a validated `BindingRecord`.

    Raises `BindingRejected` (terminal) on any rejection-taxonomy failure and
    `SchemaValidationError` if the emitted record does not satisfy
    `ecai/binding_record/1.0` (fail-closed stage boundary).
    """
    root = Path(dataset_root)
    if not root.is_dir():
        raise BindingRejected(
            REASON_MISSING_ARTIFACT, path=str(root), detail="dataset root not found"
        )

    texts = _read_required(root)

    # step 2 + 3: parse, canonicalize, verify every listed file.
    entries = V.parse_manifest(texts[MANIFEST_RELPATH])
    V.verify_members(root, entries)
    entry_count, distinct_count = V.manifest_counts(entries)
    digest = V.composite_digest(entries)

    # step 5: readiness gate (authoritative).
    order, per_game, eligible, excluded = _parse_readiness(texts[_READINESS_RELPATH])

    # step 6: prose cross-checks (soft).
    table = _parse_md_table(texts[_DATASET_BINDING_RELPATH])
    dataset_id = _strip_ticks(table.get("Dataset", "")) or root.name
    slate_date = _strip_ticks(table.get("Slate date", "")) or _derive_slate_date(order)
    if not _DATE_RE.match(slate_date):
        raise BindingRejected(
            REASON_MALFORMED_MANIFEST,
            path=_DATASET_BINDING_RELPATH,
            detail=f"unparseable slate date: {slate_date!r}",
        )

    freeze_timestamp = _normalize_rfc3339(table.get("Freeze built (UTC)", ""))
    if freeze_timestamp is None:
        anchor_table = _parse_md_table(texts[_ANCHOR_RELPATH])
        freeze_timestamp = _normalize_rfc3339(anchor_table.get("Freeze built", ""))
    if freeze_timestamp is None:
        raise BindingRejected(
            REASON_MALFORMED_MANIFEST,
            path=_DATASET_BINDING_RELPATH,
            detail="freeze timestamp unparseable in DATASET_BINDING.md and ANCHOR_COMMIT",
        )

    if expect_slate is not None and expect_slate != slate_date:
        raise BindingRejected(
            REASON_SLATE_DATE_MISMATCH,
            path="slate.date",
            detail=f"expected {expect_slate}, binding says {slate_date}",
        )

    if not eligible:
        raise BindingRejected(
            REASON_EMPTY_ELIGIBLE_SET,
            detail="no READY_FOR_KIMI games in readiness CSV",
        )

    discrepancies = _cross_check(
        root=root,
        dataset_id=dataset_id,
        slate_date=slate_date,
        frozen_prose=_first_int(table.get("Frozen games", "")),
        excluded_prose=_first_int(table.get("Excluded games", "")),
        anchor_count=_extract_anchor_file_count(texts[_ANCHOR_RELPATH]),
        entry_count=entry_count,
        eligible=eligible,
        excluded=excluded,
        per_game=per_game,
    )

    source_artifacts = [
        {"relpath": relpath, "sha256": V.sha256_file(root / relpath)}
        for relpath in REQUIRED_ARTIFACTS
    ]

    record = BindingRecord(
        run_id=run_id or str(uuid.uuid4()),
        produced_at=_utc_now_rfc3339(),
        dataset_id=dataset_id,
        freeze_timestamp=freeze_timestamp,
        slate_date=slate_date,
        game_count=len(order),
        join_key_format=_JOIN_KEY_FORMAT,
        composite_digest=digest,
        manifest_path=MANIFEST_RELPATH,
        manifest_entry_count=entry_count,
        manifest_distinct_digests=distinct_count,
        eligible_games=eligible,
        per_game=per_game,
        excluded_matchups=excluded,
        source_artifacts=source_artifacts,
        prose_discrepancies=discrepancies,
        input_artifact_hashes=[artifact["sha256"] for artifact in source_artifacts],
    )

    payload = record.to_dict()

    # fail-closed stage boundary: never emit an artifact that fails its contract.
    try:
        validate(payload, BINDING_SCHEMA_VERSION)
    except SchemaValidationError as exc:
        raise SchemaValidationError(BINDING_SCHEMA_VERSION, exc.errors) from exc

    if out_root is not None:
        run_dir = Path(out_root) / record.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "binding.json").write_text(
            json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8"
        )

    return record
