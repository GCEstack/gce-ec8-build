# IMPLEMENTATION_CHOICES.md — BRIEF-20260906-EC8-W2

Every §4 discretion actually used, registered (Wave 0 §8 register style, per brief §7).
No silent choices. Zero silent substantive deviations.

| Surface (brief §4 / Calibro §M3 / Chiave v1.1 §A) | Choice made | Reversible? | Notes |
|---|---|---|---|
| Isolation mechanism (EX-1..6) | Per-analyst sandbox = own fs root under `.harness\iso\<run>\<slot>` + scrubbed env namespace; a `python -m ec8wave2.iso` worker runs as a REAL separate subprocess (sys.executable) to prove the process/env/fs boundary. Network handle is None and no networking import exists. | Reversible | Subprocess evidence: worker writes marker strictly inside its own argv root; parent-only secret never visible in child env. |
| Session-id plumbing (EX-3 / CD-4) | `SessionRegistry` keys a session by `(run_id, slot)` so intra-run Stage 1/3 share and inter-run never do; machine-check `verify_session_continuity` reports violations. | Reversible | Deterministic code only. |
| IF-2 choke point SHAPE | Single `Assembler.assemble_package`; envelope construction is module-internal; bypass detection counter + store-read trace for post-hoc package audit (G6 surface). No I1 content semantics, no market filter. | Reversible | Envelope slots exist structurally; filling/status semantics are Wave-2-blocked (routed). |
| Registry interfaces (PR-2 / RG-1..4) | Append-only JSONL `Registry` with per-kind required-field validation; `EX2Preflight` structural heterogeneity check runs pre-spend; `RegistryPinner` snapshots versions (RG-4). Content = fixture/empty, status `fixture` only (RQ-14 stays unsatisfied). | Reversible | Registry rows are write-once; retire = new row, never an update/delete. |
| Checkpoint store (CK-1..4) | Append-only gate-checkpoint rows; resume reads LAST PASSED gate and restores counters as-of-gate (no reset, no doubling); crash-restart cap = 2 then exclusion with mechanical reason `crash_restart_limit` (no FC class fabricated, D19). T-bound hook fails closed until clock authority configured. | Reversible | Counter-survival proven across a crash + resume in demo C5. |
| Artifact validator (AS-1..4) | Nine-section structural validator + header version fields; AS-2 major-vs-additive rule; AS-3 terminal pointer reads artifact id from header and never promotes Morning on failed Pre-Game; AS-4 SHA-256 seal + tamper detect + reseal-with-new-id. | Reversible | Structural only. |
| VL/NO adapter shells | Wire shape `{layer,state,failure_class?,test_id?,detail}`; ANY failure_class/test_id VALUE raises (FC enum v1.0 unpinned). NO adapter accepts exactly the four-component input contract; fifth input / `Contradicted` from caller blocked (fail closed). | Reversible | Fail-closed placeholders, never silent defaults. |
| W1 metering carry-forward (W2-C8) | Wave 2 imports `ec8wave1` (read-only; wave1 package on sys.path) — no wave0/wave1 source mutation. L2 adapter routes provider work through the W1 `Provider.execute` execution point; no caller-side ledger writes. | Reversible (dependency: wave1 frozen under adjudication) | No-retrofit OB-3 continues into construction. |
| Contamination (CD-1..4) | CanaryProgram (>=3 surfaces, 2^64+ space, cross-scan, strip), Fingerprinter (investigation flag only, never auto-exclusion), PairwiseSampler, continuity delegate to session hook. | Reversible | Supplemental demo X1. |
| L3 fallback (FB-1..3) | `FallbackProvider` wraps two W1 mocks at the provider-abstraction layer; whole-run auto-switchover on primary failure; both-fail = blocked (I5); switchover events `{primary,fallback,trigger,ts,affected}`; eligibility structural only, approval never assumed. | Reversible | Supplemental demo X2. |
| Test harness | `verify_w2.py` asserts brief §5 W2-C1..C10; plain script, no pytest dependency. | Reversible | Replayable evidence. |
| Subordinate coder packets | **Not used** — single accountable executor (Keel). | Reversible | P8 = yes permitted; not needed. |
| Directory layout inside wave2 | Sibling `wave2\` (package `ec8wave2\`, `verify_w2.py`, `.gitignore`, `.harness\`). No new home-root. Nothing outside authorized repo. | Reversible | wave0/ + wave1/ untouched (sibling). |

## NOT chosen (deliberately out of scope / STOP-ROUTE)
- **No semantic default encoded** for any brief §2 out-of-scope surface: Pass override, Contradicted assignment, sufficiency formula (D13), gap/status enums (D08/D06), market-denial vocabulary (D09), market taxonomy/temporal semantics (D10), FC enum VALUES (Chiave FC-1 — container/wire only), ran_n-on-retry / exclusion-record shape (D07/D19), canary-in-package policy, CH bounds tables (RG-3). All are represented as absent or fail-closed raising placeholders routed to their owner.
- **No live L1/L2/L3 execution, no live provider call, no Profile A/V assumption, no OpenRouter, no RQ-14 claim.** Everything runs through W1 MockProvider.
- **No wave0/ or wave1/ source or evidence modification.**
- No production `update`/`delete` on committed ledger/registry/checkpoint rows anywhere.
- No fabrication of canary "policy" (rate/cadence = Talon), fingerprint thresholds (empirical, Luce audit), or registry content (Luce/Governance/Kimi/Talon designated).

## Declaration
All choices registered. No silent substantive deviation from Calibro §M3, Chiave v1.1 §A, or A0 Phase 2 contracts. See DEVIATIONS.md.
