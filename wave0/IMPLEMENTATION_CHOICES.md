# IMPLEMENTATION_CHOICES.md — BRIEF-20260906-EC8-W0

Every §5-left-column / §4.7 discretion actually used, registered (spec §4.7 / §7 design
obedience). No silent choices. Zero silent substantive deviations.

| Surface (§5 left column) | Choice made | Reversible? | Notes |
|---|---|---|---|
| Language / framework | **Python 3.14.2** (stdlib only; no third-party deps) | Reversible | Pinned by Talon (P9). Test runner = plain script, no pytest dependency. |
| Store product | **Filesystem**, append-only. Committed items = immutable JSON files keyed by `content_sha256` under `<root>/objects/<content_sha256>.json`. No mutable index (committed set is derived by scanning immutable `objects/`). | Reversible | Satisfies DA-1..5. Nothing committed is ever rewritten. |
| Canonical serializer | `ec8wave0/serializer.py`: 9 required fields in fixed order; timestamps → RFC 3339 UTC (`Z`); `content` canonicalized (JSON sorted keys / base64 marker for bytes); `content_sha256` and `evidence_id` excluded from hash. Same function used for write and verify. | Reversible | Deterministic + documented. Tests recompute via the public `sha256_hex` (spec W0-T06). |
| Backup file format | Snapshot directory `<root>/backups/<backup_id>/`: copy of `objects/` + `MANIFEST.json` (per-file SHA-256). `manifest_hash` = SHA-256 of canonical MANIFEST bytes. | Reversible | `backup()` returns `{status, backup_id, manifest_hash}`. |
| `evidence_id` vs hash-as-locator | **Hash-as-locator.** `content_sha256` is the locator. `evidence_id`, if supplied, is stored as an optional synonym and is excluded from the hash input (per spec §4.2). | Reversible | Fixture items omit `evidence_id`; fixture `data_class` if supplied would be preserved verbatim, never policed. |
| Directory layout inside authorized repo | Repo `Desktop\GCE_DON\GCE_EC8\GCE_EC8_Build\`; Wave 0 code under `wave0\` (package `ec8wave0\`, tests `tests\`, disposable harness `.harness\`). No new home-root folder. | Reversible | Nothing written outside the authorized repo (P1). |
| Test harness | Plain Python script `tests/test_w0_suite.py` mapping results to W0-T01..W0-T18; runs against a **disposable** harness store `.harness\suite_store\`. | Reversible | Predetermined test IDs preserved; extra assertions allowed by spec §6. |
| Subordinate coder packets | **Not used.** Single accountable executor (Keel). | Reversible | P8 = yes permitted, but no cross-packet decomposition was needed for this bounded build. |
| Timestamp representation | Timezone-aware only; rejected otherwise (SchemaGate). RFC 3339 UTC for hashing/storage. | Reversible | Required by spec §4.2 (timezone-aware timestamps). |

## NOT chosen (deliberately out of scope / STOP-ROUTE)
- `reliability_tier` closed enum — **NOT encoded** (STOP/ROUTE → Kimi). Stored as non-empty string only; fixture strings are data.
- `data_class` taxonomy / market policy — **NOT enforced** (STOP/ROUTE → Kimi + Chiave). If present, preserved verbatim.
- No provider/model/Profile A/V, no IF-2/IF-3, no G4/canary/normalizer, no Wave 1 ledger (all out of scope §3.3).
- No production `update`/`delete` of committed items on any interface (spec §4.3, W0-T11).

## Declaration
All choices above are registered. No silent substantive deviation from the controlling
specification (Calibro Wave 0 package) was made. See DEVIATIONS.md.
