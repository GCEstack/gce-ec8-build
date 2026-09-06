"""EvidenceStore — Wave 0 append-only, content-addressed, integrity-checked store (spec §4).

Design (registered discretion):
  * Store product: filesystem. Committed items are immutable JSON files keyed by
    `content_sha256` under `<root>/objects/<content_sha256>.json`.
  * No mutable index. The set of committed items is derived by scanning the immutable
    `objects/` directory, so duplicate detection and read-by-identity never require
    mutating a committed artifact. Nothing committed is ever rewritten.
  * Backups live under `<root>/backups/<backup_id>/`: a snapshot copy of `objects/` plus a
    MANIFEST.json (per-file SHA-256). `manifest_hash` is the SHA-256 of the canonical
    MANIFEST bytes.
  * `restore` replaces the live store from a snapshot (whole-store recovery, DA-5). This is
    the only sanctioned replace path and operates on whole store; there is NO per-item
    update/delete anywhere on the public interface (spec §4.3, W0-T11).

Public interface: write / read / verify / backup / restore / list_items / object_count.
No update. No delete of a committed item.
"""

from __future__ import annotations

import json
import shutil
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import serializer as ser
from . import schema_gate as gate

_STATUS_COMMITTED = "committed"
_STATUS_REJECTED = "rejected"
_STATUS_FOUND = "found"
_STATUS_NOT_FOUND = "not_found"
_STATUS_OK = "ok"
_STATUS_TAMPER = "tamper_or_mismatch"

_BYTES_MARKER = "__ec8_bytes_b64__"


class EvidenceStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.objects_dir = self.root / "objects"
        self.backups_dir = self.root / "backups"
        self.objects_dir.mkdir(parents=True, exist_ok=True)
        self.backups_dir.mkdir(parents=True, exist_ok=True)

    # ---------- encoding helpers (immutable file representation) ----------
    @staticmethod
    def _encode_content(content: Any) -> Any:
        if isinstance(content, bytes):
            import base64

            return {_BYTES_MARKER: base64.b64encode(content).decode("ascii")}
        return content

    @staticmethod
    def _decode_content(encoded: Any) -> Any:
        if isinstance(encoded, dict) and set(encoded.keys()) == {_BYTES_MARKER}:
            import base64

            return base64.b64decode(encoded[_BYTES_MARKER])
        return encoded

    def _to_record(self, item: dict[str, Any], content_sha256: str) -> dict[str, Any]:
        """Build the persisted record (canonical required fields + integrity + optionals)."""
        record: dict[str, Any] = {}
        for field in ser.REQUIRED_FIELDS:
            if field == "content":
                record["content"] = self._encode_content(item["content"])
            elif field in ("snapshot_time", "acquired_at", "expires_at"):
                record[field] = ser.format_timestamp(item[field])
            else:
                record[field] = item[field]
        record["content_sha256"] = content_sha256
        if "evidence_id" in item:
            record["evidence_id"] = item["evidence_id"]
        if "data_class" in item:
            record["data_class"] = item["data_class"]
        return record

    def _from_record(self, record: dict[str, Any]) -> dict[str, Any]:
        record = dict(record)
        record["content"] = self._decode_content(record.get("content"))
        return record

    # ---------- committed-item enumeration (derived, read-only) ----------
    def _object_files(self) -> list[Path]:
        return sorted(p for p in self.objects_dir.iterdir() if p.is_file() and p.suffix == ".json")

    def _load_record_file(self, path: Path) -> dict[str, Any] | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _load_by_hash(self, content_sha256: str) -> dict[str, Any] | None:
        """Load a committed object by hash. A PRESENT-but-corrupt file is reported as a
        special sentinel so the caller can surface it as tamper (W0-T08 / I4) rather than
        not_found, because a byte-flip can corrupt JSON parseability."""
        path = self.objects_dir / f"{content_sha256}.json"
        if not path.exists():
            return None
        rec = self._load_record_file(path)
        if rec is None:
            return {"__tamper__": True}
        return rec

    def _identity_key(self, record: dict[str, Any]) -> tuple[str, str, str]:
        return (record["entity"], record["attribute"], record["snapshot_time"])

    def list_items(self) -> list[dict[str, Any]]:
        """Committed items as python records (content decoded). Read-only enumeration."""
        out: list[dict[str, Any]] = []
        for p in self._object_files():
            rec = self._load_record_file(p)
            if rec:
                out.append(self._from_record(rec))
        return out

    def object_count(self) -> int:
        return len(self._object_files())

    def _find_by_identity(self, entity: str, attribute: str, snapshot_time: Any) -> dict[str, Any] | None:
        snap = ser.format_timestamp(snapshot_time)
        for p in self._object_files():
            rec = self._load_record_file(p)
            if rec and self._identity_key(rec) == (entity, attribute, snap):
                return self._from_record(rec)
        return None

    # ---------- write ----------
    def write(self, item: dict[str, Any]) -> dict[str, Any]:
        reason = gate.validate_required_fields(item) or gate.validate_timestamps_aware(item)
        if reason:
            return {"status": _STATUS_REJECTED, "reason": reason}
        reason = gate.validate_run_type(item)
        if reason:
            return {"status": _STATUS_REJECTED, "reason": reason}

        computed = ser.sha256_hex(item)
        supplied = item.get("content_sha256")
        if supplied is not None and supplied != computed:
            return {"status": _STATUS_REJECTED, "reason": gate._HASH_MISMATCH}

        # duplicate identity check (write-once): scan immutable committed objects
        existing = self._find_by_identity(item["entity"], item["attribute"], item["snapshot_time"])
        if existing is not None:
            return {"status": _STATUS_REJECTED, "reason": gate._DUPLICATE_IDENTITY}

        record = self._to_record(item, computed)
        dest = self.objects_dir / f"{computed}.json"
        if not dest.exists():  # append-only: never overwrite committed bytes
            dest.write_text(
                json.dumps(record, ensure_ascii=True, sort_keys=False, separators=(",", ":")),
                encoding="utf-8",
            )
        identity = {
            "entity": record["entity"],
            "attribute": record["attribute"],
            "snapshot_time": record["snapshot_time"],
        }
        return {
            "status": _STATUS_COMMITTED,
            "content_sha256": computed,
            "identity": identity,
        }

    # ---------- read ----------
    def read(self, locator: Any) -> dict[str, Any]:
        """Read by content_sha256 (str) or identity triple (dict with entity/attribute/snapshot_time)."""
        rec: dict[str, Any] | None = None
        if isinstance(locator, str):
            rec = self._load_by_hash(locator)
        elif isinstance(locator, dict):
            rec = self._find_by_identity(
                locator["entity"], locator["attribute"], locator["snapshot_time"]
            )
        if rec is None:
            return {"status": _STATUS_NOT_FOUND}
        if rec.get("__tamper__"):
            return {"status": _STATUS_TAMPER}
        # read must never present tampered bytes as ok (I4): integrity check first.
        check = self._verify_record(rec)
        if check["status"] != _STATUS_OK:
            return {"status": _STATUS_TAMPER}
        return {"status": _STATUS_FOUND, "item": self._from_record(rec)}

    # ---------- integrity ----------
    def _verify_record(self, rec: dict[str, Any]) -> dict[str, Any]:
        stored_hash = rec.get("content_sha256")
        if not gate.validate_content_sha256_format(stored_hash or ""):
            return {"status": _STATUS_TAMPER}
        # Reconstruct the write-side item so hashing sees the SAME content type/bytes that
        # produced the stored hash (bytes content must be decoded before re-hash).
        item: dict[str, Any] = {
            field: rec[field]
            if field != "content"
            else self._decode_content(rec.get("content"))
            for field in ser.REQUIRED_FIELDS
        }
        recomputed = ser.sha256_hex(item)  # excludes content_sha256 / evidence_id
        if stored_hash != recomputed:
            return {"status": _STATUS_TAMPER}
        return {"status": _STATUS_OK}

    def verify(self, locator: Any) -> dict[str, Any]:
        rec: dict[str, Any] | None = None
        if isinstance(locator, str):
            rec = self._load_by_hash(locator)
        elif isinstance(locator, dict):
            rec = None
            for p in self._object_files():
                r = self._load_record_file(p)
                if r and "entity" in locator and self._identity_key(r) == (
                    locator.get("entity"),
                    locator.get("attribute"),
                    ser.format_timestamp(locator.get("snapshot_time")),
                ):
                    rec = r
                    break
        if rec is None:
            return {"status": _STATUS_NOT_FOUND}
        if rec.get("__tamper__"):
            return {"status": _STATUS_TAMPER}
        return self._verify_record(rec)

    # ---------- backup / restore ----------
    def _new_backup_id(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def backup(self, destination: str | Path | None = None) -> dict[str, Any]:
        backup_id = self._new_backup_id()
        dest = Path(destination) if destination else self.backups_dir
        dest.mkdir(parents=True, exist_ok=True)
        snap = dest / backup_id
        obj_snap = snap / "objects"
        obj_snap.mkdir(parents=True, exist_ok=True)
        manifest: dict[str, str] = {}
        for p in self._object_files():
            data = p.read_bytes()
            target = obj_snap / p.name
            target.write_bytes(data)
            manifest[p.name] = hashlib.sha256(data).hexdigest()
        manifest_bytes = json.dumps(
            manifest, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        (snap / "MANIFEST.json").write_text(manifest_bytes.decode("utf-8"), encoding="utf-8")
        return {"status": _STATUS_OK, "backup_id": backup_id, "manifest_hash": manifest_hash}

    def restore(self, backup_id: str, destination: str | Path | None = None) -> dict[str, Any]:
        src = (Path(destination) if destination else self.backups_dir) / backup_id
        obj_src = src / "objects"
        if not obj_src.is_dir():
            return {"status": "error", "reason": "backup_id_not_found"}
        # whole-store recovery: wipe live objects, replace from snapshot (DA-5 restore).
        for p in self._object_files():
            p.unlink()
        for p in obj_src.iterdir():
            if p.is_file() and p.suffix == ".json":
                shutil.copyfile(p, self.objects_dir / p.name)
        return {"status": _STATUS_OK, "item_count": self.object_count()}
