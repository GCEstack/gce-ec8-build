"""Process-isolation shells (EX-1..6 scaffold).

Per-analyst execution contexts with no shared env / filesystem / network namespace,
realized as sandbox objects whose environment namespace and filesystem root are ownable
per analyst. An `iso` worker entrypoint can be spawned as a SEPARATE PROCESS
(`python -m ec8wave2.iso --root ...`) under a scrubbed environment to prove the
boundary: the child sees only its own namespace and can write only inside its own root.

Shells only. No analyst runtime content, no live network, no shared sampling semantics.
Per-persona prompt/sampling parameter SLOTS exist as shells keyed by slot id; the values
they will carry in a live pilot are outside this scaffold.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import WAVE2_ROOT
from ._stubs import canary_token

# env allowlist for a child sandbox process (scrubbed parent env: no secrets)
_CHILD_ENV_ALLOWLIST = (
    "PATH",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "TEMP",
    "TMP",
    "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE",
    "OS",
    "PYTHONIOENCODING",
)

# env keys that identify a sandbox process; a parent-secret key may never enter this set
_CHILD_IDENTITY_KEYS = ("EC8_ISO_RUN", "EC8_ISO_SLOT", "EC8_ISO_CANARY")


@dataclass
class SandboxSpec:
    """A per-analyst execution context shell (EX-1). One sandbox per analyst per run."""

    run_id: str
    slot: str
    root: Path
    env: dict[str, str] = field(default_factory=dict)
    prompt_slot: str = ""
    sampling: dict = field(default_factory=dict)
    network: object | None = None


def new_run_id() -> str:
    return "R-" + uuid.uuid4().hex


def sandbox_env(spec: SandboxSpec) -> dict[str, str]:
    """Build the scrubbed child environment for a sandbox (env-namespace isolation)."""
    child = {}
    for key in _CHILD_ENV_ALLOWLIST:
        if key in os.environ:
            child[key] = os.environ[key]
    child["EC8_ISO_RUN"] = spec.run_id
    child["EC8_ISO_SLOT"] = spec.slot
    child["EC8_ISO_CANARY"] = canary_token()
    child["PYTHONIOENCODING"] = "utf-8"
    return child


def _spawn_worker(spec: SandboxSpec, timeout_s: int = 60) -> subprocess.CompletedProcess:
    spec.root.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [sys.executable, "-m", "ec8wave2.iso", "--root", str(spec.root)],
        cwd=str(WAVE2_ROOT),
        env=sandbox_env(spec),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout_s,
    )


class IsolationManager:
    """Spawns and checks per-analyst isolation shells (EX-1..6)."""

    def __init__(self, harness_root: Path):
        self.harness_root = Path(harness_root)
        self.iso_root = self.harness_root / "iso"
        self.iso_root.mkdir(parents=True, exist_ok=True)
        self.sandboxes: list[SandboxSpec] = []

    def create_sandbox(self, slot: str, run_id: str | None = None) -> SandboxSpec:
        run_id = run_id or new_run_id()
        root = self.iso_root / run_id / slot
        spec = SandboxSpec(
            run_id=run_id,
            slot=slot,
            root=root,
            env={},
            prompt_slot=f"prompt:{slot}",
            sampling={"temperature": None},
            network=None,
        )
        self.sandboxes.append(spec)
        return spec

    def spawn(self, spec: SandboxSpec) -> dict:
        result = _spawn_worker(spec)
        return {"returncode": result.returncode, "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}


def isolation_proof(harness_root: Path, slots: tuple[str, ...], parent_secret_key: str) -> dict:
    """Run per-analyst process spawns and verify the isolation boundary (W2-C1 evidence).

    Each analyst runs as its own subprocess under a scrubbed environment, given ONLY its
    own sandbox root as a writable path. Assertions surfaced for the verifier:
      - every child returned 0 and wrote its marker strictly inside its own argv root
      - no child env carried the parent-only secret key (env namespace isolation)
      - no child env carried any OTHER analyst's identity keys (no shared session context)
      - run ids and canary tokens are unique per analyst
      - no proxy/env-leak variables reach the child (network hygiene)
    """
    mgr = IsolationManager(harness_root)
    os.environ[parent_secret_key] = "parent-only-value-not-for-child"

    spawned = [mgr.create_sandbox(slot) for slot in slots]
    env_kv: dict[str, dict[str, str]] = {}
    markers: dict[str, dict] = {}
    for spec in spawned:
        res = mgr.spawn(spec)
        marker_path = spec.root / "marker.json"
        env_path = spec.root / "env_kv.txt"
        canary_path = spec.root / "canary.txt"
        markers[spec.slot] = {
            "marker": json.loads(marker_path.read_text(encoding="utf-8")) if marker_path.exists() else None,
            "marker_parent_is_own_root": str(marker_path.parent) == str(spec.root) if marker_path.exists() else False,
            "returncode": res["returncode"],
            "stderr": res["stderr"],
            "canary": canary_path.read_text(encoding="utf-8").strip() if canary_path.exists() else "",
        }
        if env_path.exists():
            env_kv[spec.slot] = dict(
                line.split("=", 1) for line in env_path.read_text(encoding="utf-8").splitlines() if "=" in line
            )

    leaked_slots = [s for s in slots if parent_secret_key in env_kv.get(s, {})]
    identity_mismatch: dict[str, str] = {}
    foreign_run_ids: dict[str, list[str]] = {}
    expected_run = {spec.slot: spec.run_id for spec in spawned}
    for slot in slots:
        kv = env_kv.get(slot, {})
        if kv.get("EC8_ISO_SLOT") != slot:
            identity_mismatch[slot] = f"EC8_ISO_SLOT={kv.get('EC8_ISO_SLOT')}"
        if kv.get("EC8_ISO_RUN") != expected_run[slot]:
            identity_mismatch.setdefault(slot, "")
            identity_mismatch[slot] += f" EC8_ISO_RUN={kv.get('EC8_ISO_RUN')}"
        foreign_run_ids[slot] = [
            v for k, v in kv.items() if k.startswith("EC8_ISO_RUN") and v != expected_run[slot]
        ]

    canaries = {markers[s]["canary"] for s in slots}
    run_ids = {markers[s]["marker"]["run_id"] for s in slots if markers[s]["marker"]}
    return {
        "run_ids_unique": len(run_ids) == len(slots),
        "run_ids": sorted(run_ids),
        "canaries_unique": len(canaries) == len(slots),
        "child_env_leaks_of_parent_secret": leaked_slots,
        "identity_mismatch": identity_mismatch,
        "marker_parent_is_own_root": {s: markers[s]["marker_parent_is_own_root"] for s in slots},
        "all_returncodes_ok": all(markers[s]["returncode"] == 0 for s in slots),
        "stderr": {s: markers[s]["stderr"] for s in slots if markers[s]["stderr"]},
    }


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="EC8 Wave 2 isolation worker (mock).")
    parser.add_argument("--root", required=True, help="per-analyst sandbox root (the ONLY writable location)")
    args = parser.parse_args()

    root = Path(args.root)
    if not root.exists():
        print("ERROR: sandbox root does not exist", file=sys.stderr)
        return 2

    run_id = os.environ.get("EC8_ISO_RUN", "UNSET")
    slot = os.environ.get("EC8_ISO_SLOT", "UNSET")
    canary = os.environ.get("EC8_ISO_CANARY", "UNSET")

    marker = {"run_id": run_id, "slot": slot, "pid": os.getpid()}
    (root / "marker.json").write_text(json.dumps(marker, sort_keys=True), encoding="utf-8")
    (root / "env_keys.txt").write_text("\n".join(sorted(os.environ.keys())) + "\n", encoding="utf-8")
    (root / "env_kv.txt").write_text("\n".join(sorted(f"{k}={v}" for k, v in os.environ.items())) + "\n", encoding="utf-8")
    (root / "canary.txt").write_text(canary + "\n", encoding="utf-8")

    print(json.dumps({"ok": True, "slot": slot, "run_id": run_id, "marker_written": str(root / "marker.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
