# IMPLEMENTATION_CHOICES.md — BRIEF-20260906-EC8-W1

Every §4 discretion actually used, registered (Wave 0 §8 register style, per brief §7).
No silent choices. Zero silent substantive deviations.

| Surface (brief §4 / Calibro §M2) | Choice made | Reversible? | Notes |
|---|---|---|---|
| HTTP-client / transport | **None — in-process mock provider** (no HTTP at all) | Reversible | Brief §4 permits "no HTTP at all". Mock is local; no network egress, $0. |
| Retry/backoff behavior | Provider abstraction executes attempts; on transient failure, logs one `retry` row then re-attempts up to `max_attempts`; no retry on non-transient. Backoff schedule configurable (mock run uses `(0,0)` for speed/determinism). Calibro §F reference honored as shape; live timings out of scope. | Reversible | Retries/failures are EXTRA ledger rows (brief §5.5 / §M2). |
| Mock catalog | Python dict fixture mirroring Calibro readiness §E roster as NON-approved data. `list_models()` mimics `GET /v1/models` contract locally. No live gateway, no ID-availability assertion. | Reversible | RQ-14 NOT satisfied by design (brief §4). |
| Ledger storage product | Append-only JSONL file. Row id = uuid; row_sha256 recorded for integrity. No update/delete on public interface (W1 §5.8). | Reversible | Independent of Wave 0 package (W1 non-dependency). |
| Observability emit mechanism | In-process `Emitter` writing append-only JSONL events carrying OB-2 granularity keys (component/run/layer/source/analyst_slot). No external sink (fully replayable, no network). | Reversible | OB-5 content metrics deferred (Wave 2+); not fabricated. |
| Where the meter lives (OB-3) | Meter + emit are INSIDE `Provider.execute()` — the single execution point. Calling/orchestration layer never meters. | Reversible (but design-critical) | No-retrofit property proven by `demo_no_retrofit` (W1-C4). |
| Directory layout inside wave1 | Repo `GCE_EC8_Build\`; Wave 1 under `wave1\` (package `ec8wave1\`, verify `verify_w1.py`, disposable `.harness\`). No new home-root. Nothing outside authorized repo. | Reversible | wave0/ untouched (sibling only). |
| Test harness | `verify_w1.py` asserts brief §5 criteria W1-C1..C9; plain script, no pytest dependency. | Reversible | Replayable evidence. |
| Subordinate coder packets | **Not used** — single accountable executor (Keel). | Reversible | P8 = yes permitted; not needed. |
| run_type / cadence model | 1/26/26 reference topology as `(Overnight 1, Morning 26, PreGame 26)` = 53 call points, mirroring M cadence / A0 OB-4. Fixture only. | Reversible | Analyst slot labels are fixture granularity, NOT an approval of any roster (RQ-14 / Profile A-V). |

## NOT chosen (deliberately out of scope / STOP-ROUTE)
- **No live Mantle/Bedrock call; no live provider ID pin** (brief §4 may-not; RQ-14 stays unsatisfied).
- **No Profile A/V assumption** — mock roster is fixture, not an approval. No OpenRouter.
- **No Wave 2 semantic defaults** (IF-2 assembler, IF-3 gap router, normalizer/sufficiency meaning, G4/FC/canary content, gap-status enums, Pass-override, L3 live fallback). None fabricated.
- No store-only work already owned by Wave 0 (W1 independent).
- No production `update`/`delete` of committed ledger rows anywhere.

## Declaration
All choices registered. No silent substantive deviation from Calibro §M2 or A0 contracts.
See DEVIATIONS.md.
