"""Phase 1 — WS5 binding acceptance (G1): T-11, T-12.

Covers the real 2026-09-15 freeze plus a synthetic mini-freeze used to exercise
the rejection taxonomy, runtime-derived counts, and the read-only guarantee.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ecai.binding import BindingRejected, bind
from ecai.binding.models import (
    BINDING_SCHEMA_VERSION,
    REASON_EMPTY_ELIGIBLE_SET,
    REASON_HASH_MISMATCH,
    REASON_MALFORMED_MANIFEST,
    REASON_MISSING_ARTIFACT,
    REASON_SLATE_DATE_MISMATCH,
)
from ecai.binding.verify import (
    canonical_manifest_bytes,
    composite_digest,
    manifest_counts,
    parse_manifest,
    sha256_file,
)
from ecai.schemas import validate

FREEZE = Path(
    r"C:\Users\Dekan AI Brother\Desktop\mlb-data-system"
    r"\EC8_MLB_COMMON_FROZEN_DATASET_2026-09-15_EARLYCLUSTER-FROZEN-v1"
)

READINESS_REL = "governance/EARLY_CLUSTER_READINESS_2026-09-15.csv"
ANCHOR_REL = "governance/ANCHOR_COMMIT_EARLYCLUSTER_2026-09-15.md"
MANIFEST_REL = "control/DATASET_HASHES_SHA256.txt"


# --------------------------------------------------------------------------- helpers
def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _snapshot(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def build_freeze(
    tmp_path: Path,
    *,
    dataset_name: str = "MINI_FREEZE",
    slate: str = "2026-09-15",
    members: list[tuple[str, str]] | None = None,
    statuses: list[tuple[str, str]] | None = None,
    anchor_count: int | None = None,
    freeze_ts: str = "2026-09-15T22:03Z",
) -> Path:
    """Build a synthetic, hash-consistent freeze tree."""
    root = tmp_path / dataset_name
    if members is None:
        members = [
            ("frozen/aaa.csv", "a,b\n1,2\n"),
            ("frozen/bbb.csv", "x\n3\n"),
        ]
    if statuses is None:
        statuses = [
            (f"Away@Home {slate}", "READY_FOR_KIMI"),
            (f"Late@Game {slate}", "DATA_INCOMPLETE — lineups(9/18)"),
        ]
    for rel, content in members:
        _write(root / rel, content)

    frozen = sum(1 for _g, s in statuses if s == "READY_FOR_KIMI")
    excluded = len(statuses) - frozen
    binding_md = (
        "# DATASET BINDING — MINI\n\n"
        "| Field | Value |\n"
        "|---|---|\n"
        f"| Dataset | `{dataset_name}` |\n"
        f"| Slate date | {slate} |\n"
        f"| Freeze built (UTC) | {freeze_ts} |\n"
        f"| Frozen games | {frozen} (`READY_FOR_KIMI`) |\n"
        f"| Excluded games | {excluded} (`DATA_INCOMPLETE`) |\n"
    )
    _write(root / "DATASET_BINDING.md", binding_md)

    csv_lines = ["game,first_pitch_pt,first_pitch_et,minutes_to_first_pitch,status"]
    for game, status in statuses:
        csv_lines.append(f"{game},15:40,18:40,37,{status}")
    _write(root / READINESS_REL, "\n".join(csv_lines) + "\n")

    anchor_lines = ["# ANCHOR COMMIT — MINI", f"**Freeze built:** {freeze_ts}"]
    if anchor_count is not None:
        anchor_lines.append(f"{anchor_count} files hashed")
    _write(root / ANCHOR_REL, "\n".join(anchor_lines) + "\n")

    listed = [rel for rel, _ in members] + [
        "DATASET_BINDING.md",
        ANCHOR_REL,
        READINESS_REL,
    ]
    manifest_lines = [
        f"{sha256_file(root / rel).upper()}  {rel}" for rel in sorted(listed)
    ]
    _write(root / MANIFEST_REL, "\n".join(manifest_lines) + "\n")
    return root


# --------------------------------------------------------------------------- real freeze
real_freeze = pytest.mark.skipif(not FREEZE.is_dir(), reason="frozen dataset not present")


@real_freeze
def test_bind_real_freeze():
    record = bind(FREEZE, expect_slate="2026-09-15")
    payload = record.to_dict()
    validate(payload, BINDING_SCHEMA_VERSION)

    assert payload["dataset_id"] == FREEZE.name
    assert payload["slate"]["date"] == "2026-09-15"
    assert payload["manifest_entry_count"] == 49
    assert payload["manifest_distinct_digests"] == 46
    assert payload["slate"]["game_count"] == 15
    assert len(payload["gate_status"]["eligible_games"]) == 12
    assert len(payload["excluded_matchups"]) == 3
    assert payload["freeze_timestamp"] == "2026-09-15T22:03:00Z"
    assert len(payload["source_artifacts"]) >= 4


@real_freeze
def test_real_freeze_prose_discrepancy_recorded():
    payload = bind(FREEZE).to_dict()
    fields = {d["field"] for d in payload["prose_discrepancies"]}
    # ANCHOR_COMMIT prose says "45 files hashed"; runtime manifest has 49.
    assert "manifest.entry_count" in fields


@real_freeze
def test_real_freeze_composite_digest_recomputes():
    manifest_text = (FREEZE / MANIFEST_REL).read_text(encoding="utf-8")
    entries = parse_manifest(manifest_text)
    payload = bind(FREEZE).to_dict()
    assert composite_digest(entries) == payload["composite_digest"]
    assert manifest_counts(entries) == (49, 46)


@real_freeze
def test_bind_real_freeze_is_read_only(tmp_path):
    before = _snapshot(FREEZE)
    bind(FREEZE, out_root=tmp_path / "runs")
    after = _snapshot(FREEZE)
    assert before == after


# --------------------------------------------------------------------------- T-11
def test_t11_composite_digest_changes_when_a_member_hash_changes(tmp_path):
    root = build_freeze(tmp_path)
    manifest_text = (root / MANIFEST_REL).read_text(encoding="utf-8")
    original = parse_manifest(manifest_text)
    baseline = composite_digest(original)

    tampered = list(original)
    victim = tampered[0]
    tampered[0] = type(victim)(
        relpath=victim.relpath, sha256="0" * 64
    )
    assert composite_digest(tampered) != baseline


def test_t11_counts_are_runtime_derived_not_hardcoded(tmp_path):
    """A 4-entry manifest must yield 4 — proving counts come from the manifest."""
    root = build_freeze(
        tmp_path,
        dataset_name="COUNT_FREEZE",
        members=[
            ("frozen/a.csv", "a\n"),
            ("frozen/b.csv", "b\n"),
            ("frozen/c.csv", "c\n"),
            ("frozen/d.csv", "d\n"),
        ],
    )
    payload = bind(root).to_dict()
    assert payload["manifest_entry_count"] == 7  # 4 members + 3 required artifacts
    assert payload["manifest_distinct_digests"] == 7


def test_t11_tampered_member_file_is_rejected(tmp_path):
    root = build_freeze(tmp_path)
    (root / "frozen/aaa.csv").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(BindingRejected) as exc:
        bind(root)
    assert exc.value.reason == REASON_HASH_MISMATCH
    assert exc.value.path == "frozen/aaa.csv"


def test_manifest_canonical_bytes_are_sorted_and_normalized(tmp_path):
    root = build_freeze(tmp_path)
    entries = parse_manifest((root / MANIFEST_REL).read_text(encoding="utf-8"))
    relpaths = [e.relpath for e in entries]
    assert relpaths == sorted(relpaths)
    assert all("\\" not in e.relpath for e in entries)
    assert all(e.sha256 == e.sha256.upper() for e in entries)
    assert canonical_manifest_bytes(entries).count(b"\n") == len(entries)


# --------------------------------------------------------------------------- T-12
def test_t12_expected_slate_mismatch(tmp_path):
    root = build_freeze(tmp_path)
    with pytest.raises(BindingRejected) as exc:
        bind(root, expect_slate="2026-09-14")
    assert exc.value.reason == REASON_SLATE_DATE_MISMATCH


def test_t12_deleted_listed_member_is_hash_mismatch(tmp_path):
    root = build_freeze(tmp_path)
    (root / "frozen/bbb.csv").unlink()
    with pytest.raises(BindingRejected) as exc:
        bind(root)
    assert exc.value.reason == REASON_HASH_MISMATCH
    assert exc.value.path == "frozen/bbb.csv"


def test_t12_missing_required_artifact(tmp_path):
    root = build_freeze(tmp_path)
    (root / "DATASET_BINDING.md").unlink()
    with pytest.raises(BindingRejected) as exc:
        bind(root)
    assert exc.value.reason == REASON_MISSING_ARTIFACT
    assert exc.value.path == "DATASET_BINDING.md"


def test_t12_malformed_manifest(tmp_path):
    root = build_freeze(tmp_path)
    (root / MANIFEST_REL).write_text(
        "not-a-valid-manifest-line\n", encoding="utf-8"
    )
    with pytest.raises(BindingRejected) as exc:
        bind(root)
    assert exc.value.reason == REASON_MALFORMED_MANIFEST


def test_t12_empty_eligible_set(tmp_path):
    root = build_freeze(
        tmp_path,
        dataset_name="EMPTY_FREEZE",
        statuses=[("Late@Game 2026-09-15", "DATA_INCOMPLETE — lineups(9/18)")],
    )
    with pytest.raises(BindingRejected) as exc:
        bind(root)
    assert exc.value.reason == REASON_EMPTY_ELIGIBLE_SET


# --------------------------------------------------------------------------- emission
def test_binding_json_emitted_and_valid(tmp_path):
    root = build_freeze(tmp_path)
    out_root = tmp_path / "runs"
    record = bind(root, out_root=out_root)
    emitted = out_root / record.run_id / "binding.json"
    assert emitted.is_file()
    payload = json.loads(emitted.read_text(encoding="utf-8"))
    validate(payload, BINDING_SCHEMA_VERSION)
    assert payload["composite_digest"] == record.composite_digest


def test_bind_does_not_write_to_freeze(tmp_path):
    root = build_freeze(tmp_path)
    before = _snapshot(root)
    bind(root, out_root=tmp_path / "runs")
    assert _snapshot(root) == before
