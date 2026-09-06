"""ec8wave0 — Wave 0 Foundation (append-only evidence store + secret isolation).

Controlling spec: EC8_Wave0_Keel_Audition_Implementation_Package_Calibro_2026-09-06.md
Brief: BRIEF-20260906-EC8-W0.  Executor: Keel (Operations Manager). Occupant: DeepSeek V4 Flash.
This package implements spec §4 components: EvidenceStore, Integrity, SchemaGate,
BackupRestore, SecretFence. No update/delete of committed items on any public interface.
"""

__version__ = "0.1.0"
