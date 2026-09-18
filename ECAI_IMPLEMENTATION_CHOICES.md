# ECAI IMPLEMENTATION CHOICES — Phase 1 (WS1+WS5) · Phase 2 (WS5 framer + WS2 DET) · Phase 3 (WS4 runtime)

**Brief:** `BRIEF-20260917-ECAI-1` · **Design:** P20 Rev 3 (Calibro) · **Executor:** Keel.
Every §5-left-column discretion actually used is registered here. No silent choices.
No methodology, architecture, contract, schema, or locked-control change (L1–L10) was made.

## Scope delivered

| Stage | Component | Status |
|---|---|---|
| 1.1 | Schemas package `ecai/schemas/` (WS1) | DONE |
| 1.2 | Binding adapter `ecai/binding/` (WS5) | DONE |
| 2.1 | Framer `ecai/framing/` + `config/markets.yaml` (WS5) | DONE |
| 2.2 | DET lane `ecai/detlane/` + `config/det_checks.yaml` (WS2) | DONE |
| 3.1 | Runtime core `ecai/runtime/` + `config/roles.bedrock.yaml` (WS4) | DONE |

Phase 4+ **not started** (per brief).

## Registered choices

| Surface | Choice | Reversible? | Notes |
|---|---|---|---|
| Language / deps | Python 3.14.2; `jsonschema>=4.18` (Draft 2020-12) + its `referencing` dep. No other third-party deps. | Reversible | P20 §2 mandates JSON Schema validation; `jsonschema` was already present in the environment. |
| Schema file count | **10 contract files** (§2.1–§2.9; §2.8 is the request/response pair) **+ `common_envelope.json`** = 11 files. "all 9 schemas" in P20 counts the §2.1–§2.9 sections. | Reversible | Matches the §2 contract list exactly. |
| Common envelope | Envelope fields are **inlined** into each contract file; `common_envelope.json` is the canonical definition and the consistency reference. | Reversible | Avoids a retrieval layer; a test asserts envelope consistency across all contracts. |
| Cross-file `$ref` | On-disk contracts keep P20 logical refs (`$ref: "ecai/evidence_item/1.0"`). The loader inlines them into local `#/$defs/<name>` at load time. | Reversible | P20 `$id: ecai/<name>/1.0` is a relative URI; local inlining makes validation deterministic with a stock validator. |
| `evidence_item` envelope | `evidence_item` carries the common envelope (its own `schema_id`/`run_id`/`produced_at`/`provenance`). | Reversible | P20 §2.3 lists `provenance`; envelope uniformity per §2 preamble. |
| Composite digest case | Member digests canonicalized **UPPERCASE** (P20 §1.2 step 2); the composite digest is the standard **lowercase** SHA-256 hex of the canonical manifest bytes. | Reversible | Deterministic and recomputable; T-11 asserts recomputation. |
| Missing listed member | Missing listed file or digest mismatch → `HASH_MISMATCH` (literal P20 §1.2 step 3). | Reversible | `MISSING_ARTIFACT` is reserved for the four required binding artifacts being unreadable (§1.2 step 1). |
| `slate.game_count` | Total readiness-CSV rows (eligible + excluded) = 15 for the 2026-09-15 freeze. | Reversible | `eligible_games` (12) and `excluded_matchups` (3) carry the breakdown. |
| Freeze timestamp fallback | `DATASET_BINDING.md` "Freeze built (UTC)" is primary; if unparseable, fall back to `ANCHOR_COMMIT` "Freeze built". Both absent → `MALFORMED_MANIFEST`. | Reversible | Avoids fabricating a timestamp. |
| Slate date source | `DATASET_BINDING.md` "Slate date"; fallback derived from readiness game-key suffixes. | Reversible | `SLATE_DATE_MISMATCH` when `--expect-slate` disagrees. |
| Read-only guarantee | Adapter reads the four artifacts + hashes listed members; writes only `runs/<run_id>/binding.json` under a caller-supplied `out_root`. | Reversible | Tested: freeze tree byte-identical before/after. |
| WS5 CLI | Delivered as `python -m ecai.binding verify --root <freeze> [--expect-slate]`; exit 0 bound / 2 rejected. | Reversible | P20 §6 WS5 deliverable. The full `ecai/cli.py` is Phase 6. |
| Test runner | `pytest` (already present). | Reversible | Phase 1 matrix: schema golden fixtures + T-11 + T-12. |

## INTERPRETATION FLAGS — for Luce LC-1 confirmation (not blockers)

These are points where P20 is silent or self-inconsistent. Build proceeded; **flagged, not silently decided**.

1. **`provenance.stage` enum gap — RESOLVED (Calibro LC1 ruling, P20 Rev 3).** Enum extended to
   `BINDING | FRAMING | DET | PANEL | CONVERGENCE | CURATOR | GATEKEEPER | TERMINAL`;
   `convergence_result` uses `stage: CONVERGENCE`, `terminal_item` uses `stage: TERMINAL`.
   No parallel `origin` field. Bounded patch: `common_envelope.json`, `convergence_result.json`,
   `terminal_item.json` + the two golden fixtures.
2. **`gatekeeper_request.curated_item` "by ref + inline".** Implemented as
   `{ref: <sha256>, inline: <curated_slate_item/1.0>}`.
3. **`det_output` check registry version.** P20 §2.4 names `det_checks_version` as a field; the
   registry itself is Phase 2 config. Schema requires the field; value is Phase 2's to supply.

## Phase 2 registered choices

| Surface | Choice | Reversible? | Notes |
|---|---|---|---|
| Framing source resolution | Factor source files are discovered by prefix under `frozen/` (`pitchers_*`, `odds_*`, …), exactly one match required; timestamps are never hard-coded. | Reversible | Frozen filenames carry fetch timestamps. |
| Factor object shape | Each factor = `{available, source_relpath, source_sha256, rows[]}`; `rows` are whitelisted **raw** columns pass-through (schema `factor` allows additional properties). | Reversible | Framer is a transcoder (T-01). |
| `available` semantics | game-keyed factors: rows present (umpire also needs a real HP umpire; weather also accepts `roof_status: CLOSED`); team-keyed factors (injuries, team_evidence): ≥1 row for away/home; odds: a non-`NOT_SET` BetMGM price. | Reversible | Drives `missing_factors` and DET sufficiency. |
| BetMGM-only enforcement | `odds_betmgm` projects only `market, selection, betmgm, betmgm_line, status, fetched_at`; other-book columns are never selected. | Reversible | Locked control L1 / T-14. |
| Game identity | `away@home` parsed from the game key; no extra slate file read for identity. | Reversible | Keeps the framer on the factor whitelist. |
| Slate metadata | `first_pitch_pt` read from `frozen/FROZEN_GAMES_*.csv`; `slate_date` from the binding record. | Reversible | Not reasoning inputs. |
| Framing provenance | `input_artifact_hashes = [binding.composite_digest] + sorted(unique factor source hashes)`. | Reversible | Ties framing to the bound freeze digest (T-07 chain). |
| Framing scope | Eligible games only (from `binding.gate_status.eligible_games`); excluded games are not framed. | Reversible | Curator handles EXCLUDED downstream. |
| DET check registry | `config/det_checks.yaml` (version `ecai.det_checks/1.0`) selects rule types implemented in `lane.py`: `factor_available`, `both_teams_present`, `lineups_complete`. | Reversible | No lean/pick/score rule exists. |
| DET provenance | `input_artifact_hashes = [sha256_json(framing_object)]`. | Reversible | Canonical-JSON hash via `ecai/hashing.py`. |
| `ecai/hashing.py` | New small utility (canonical JSON bytes + sha256) used for artifact hashing. | Reversible | Not in P20 §0 layout; benign cross-phase helper. |
| Market scope config | `config/markets.yaml` registers `moneyline` (V1 default): `odds_market: h2h`, BetMGM source columns, direction vocabulary `[HOME, AWAY]`, critical factors `[pitchers, lineups, odds_betmgm]`. | Reversible | New BetMGM scopes = config entry only (P22-2). |

## Phase 3 registered choices

| Surface | Choice | Reversible? | Notes |
|---|---|---|---|
| Region | `us-east-2` (confirmed from the account's AWS config) replaces P20's `[PROPOSED] us-east-1`. | Reversible | C2' confirmation; read-only control-plane probe. |
| Model IDs pinned | Confirmed catalog IDs replace P20 placeholders: `anthropic.claude-sonnet-4-5-20250929-v1:0`, `meta.llama3-3-70b-instruct-v1:0`, `amazon.nova-pro-v1:0`. | Reversible | P20 placeholder `anthropic.claude-sonnet-4-5` is not an exact catalog id. C2' says confirm+pin at build. |
| ≥2 families | anthropic + meta + amazon (3 families), analyst roster unchanged. | Reversible | P20 §5.1 requirement. |
| Converse + structured output | `toolConfig` with `inputSchema.json = resolved stage schema`, `toolChoice = required`; the `toolUse.input` is the parsed object. | Reversible | P20 §5.2. |
| No-bypass validation | `converse_structured` ALWAYS validates the parsed object against the stage schema before returning; invalid → parse retry → invalid result. | Reversible | No model call returns unvalidated output. |
| Parse retry | Re-asks with the validation error appended to the user turn; ≤ `parse_retries`. | Reversible | Keeps message alternation valid for real Converse. |
| Timeout semantics | Timeouts are **terminal-invalid** (not retried); they count as invalid for quorum. | Reversible | Literal P20 §5.2 ("retries on throttling/5xx … a timeout counts as invalid"). |
| Retry classification | Retryable: throttle codes + HTTP ≥ 500. Terminal: Validation/AccessDenied/NotFound/ModelError/ModelTimeout. | Reversible | Generic, no botocore import needed at classification time. |
| Quorum | `max(floor, ceil(fraction × active_roster))` in `manifest.py`; `quorum_decision` returns `STOP_BELOW_QUORUM` when unmet. | Reversible | T-05 path; NO_DATA respondents count toward `valid_analysts` (Phase 4 supplies the count). |
| Raw retention | `runs/<run_id>/raw/<stage>_<persona>_<ts>.json`, written **before** parsing (one file per attempt). | Reversible | P20 §5.2. |
| Provenance log | Append-only `runs/<run_id>/provenance.jsonl`; one record per invocation (role, persona, model_id, family, request/response hash, latency, retries, parse_retries, valid, error, manifest_hash, substitution). | Reversible | Never rewritten. |
| Substitution | Only via manifest edit; `diff_substitutions(prev, cur)` → `{substituted_for, reason: manifest_change}`; undeclared model id → `UndeclaredModelError`. | Reversible | T-13. |
| GK runtime path | `invoke_gatekeeper`; persistent invocation/schema failure → `GATEKEEPER_UNAVAILABLE` stop record, **no verdict fabricated**. | Reversible | L6; full gatekeeper runner is Phase 5. |
| Replay | `runtime/replay.py` = recorded-response reader only; full `--replay` deferred to Phase 6. | Reversible | Per LC-2 note — no replay-semantics change, no new digest scheme. |
| Replay/hash implication | Artifact hashes include `produced_at` → **run-scoped**; replay hash policy is registered for Phase 6. | Reversible | See `replay.REPLAY_HASH_IMPLICATION`. |
| Quorum location | Quorum policy functions live in `manifest.py` (no extra `quorum.py`). | Reversible | P20 §0 runtime layout kept as-is. |
| No live spend | Phase 3 tests use a mocked client; one read-only control-plane probe (no Bedrock invocation). | Reversible | Brief §2 out-of-scope: no live spend. |

## NOT chosen (deliberately out of scope)

- No panel/convergence/curator/gatekeeper-runner/terminal implementation (Phase 4+).
- No live Bedrock invocation and no live spend (mock + control-plane read only).
- No producer changes, no modification of the frozen inputs or of
  `consensus_2026-09-15.csv` / `kalshi_markets_2026-09-15.csv`.

## Declaration

All choices above are registered. No silent substantive deviation from P20 Rev 3 / the Talon brief
was made. No locked control L1–L10 was exercised or regressed by Phase 1–3 (L1/L2 enforcement, L6
GK-STOP path, L9/L10 foundations).
