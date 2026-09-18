"""WS4 — Bedrock Converse invocation layer (P20 §5.2).

Every model call goes through `converse_structured`, which ALWAYS validates the
response against the stage's JSON Schema before returning. No call may bypass
schema validation. Raw responses are retained on disk before parsing; every
invocation is appended to `provenance.jsonl`.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..hashing import sha256_json
from ..schemas import SchemaValidationError, resolved_schema, validate
from .manifest import Occupant, RuntimeManifest
from .provenance import ProvenanceLog, RawRetention
from .retry import (
    ModelInvocationError,
    ModelTimeoutError,
    RetryPolicy,
    call_with_retries,
)

DEFAULT_INFERENCE = {"maxTokens": 1024, "temperature": 0.0}
GATEKEEPER_UNAVAILABLE = "GATEKEEPER_UNAVAILABLE"


@dataclass
class ConverseResult:
    valid: bool
    parsed: dict[str, Any] | None
    raw: Any
    role: str
    persona: str | None
    model_id: str
    latency_ms: int
    retries: int
    parse_retries: int
    error: str | None = None


@dataclass
class GatekeeperOutcome:
    ok: bool
    response: dict[str, Any] | None
    stop: dict[str, Any] | None


class BedrockConverseClient:
    def __init__(
        self,
        manifest: RuntimeManifest,
        *,
        runtime_client: Any | None = None,
        run_dir: str | Path | None = None,
        sleep: Callable[[float], None] = time.sleep,
        inference: dict[str, Any] | None = None,
    ):
        self.manifest = manifest
        self.policy = RetryPolicy(
            manifest.timeout_s, manifest.max_retries, manifest.backoff_s
        )
        self._sleep = sleep
        self._client = runtime_client if runtime_client is not None else self._default_client()
        self.run_dir = Path(run_dir) if run_dir is not None else None
        self.provenance = ProvenanceLog(self.run_dir) if self.run_dir else None
        self.raw = RawRetention(self.run_dir) if self.run_dir else None
        self.inference = inference or dict(DEFAULT_INFERENCE)

    # ------------------------------------------------------------------ setup
    def _default_client(self) -> Any:
        import boto3
        from botocore.config import Config

        return boto3.client(
            "bedrock-runtime",
            region_name=self.manifest.region,
            config=Config(
                connect_timeout=self.manifest.timeout_s,
                read_timeout=self.manifest.timeout_s,
                retries={"max_attempts": 0},
            ),
        )

    def _occupant(self, role: str, persona: str | None) -> Occupant:
        if role == "gatekeeper":
            return self.manifest.gatekeeper
        occupant = self.manifest.occupant_for_persona(persona or "")
        if occupant is None:
            raise ValueError(f"no manifest occupant declares persona: {persona}")
        return occupant

    @staticmethod
    def _tool_config(schema: dict[str, Any], tool_name: str) -> dict[str, Any]:
        return {
            "tools": [
                {
                    "toolSpec": {
                        "name": tool_name,
                        "description": (
                            "Return the ECAI stage output as JSON that exactly "
                            "matches the supplied schema."
                        ),
                        "inputSchema": {"json": schema},
                    }
                }
            ],
            "toolChoice": {"tool": {"name": tool_name}},
        }

    def _record(
        self,
        *,
        role: str,
        persona: str | None,
        occupant: Occupant,
        request: dict[str, Any],
        response: Any,
        latency_ms: int,
        retries: int,
        parse_retries: int,
        valid: bool,
        error: str | None,
        substitution: dict[str, Any] | None,
    ) -> None:
        if self.provenance is None:
            return
        record: dict[str, Any] = {
            "kind": "invocation",
            "role": role,
            "persona": persona,
            "model_id": occupant.model_id,
            "family": occupant.family,
            "request_hash": sha256_json(request),
            "response_hash": sha256_json(response),
            "latency_ms": latency_ms,
            "retries": retries,
            "parse_retries": parse_retries,
            "valid": valid,
            "error": error,
            "manifest_hash": self.manifest.manifest_hash(),
            "substitution": bool(substitution),
        }
        if substitution:
            record["substituted_for"] = substitution.get("substituted_for")
            record["substitution_reason"] = substitution.get("reason")
        self.provenance.append(record)

    # ------------------------------------------------------------------ invoke
    def converse_structured(
        self,
        *,
        role: str,
        persona: str | None,
        system: str,
        user: str,
        schema_name: str,
        tool_name: str = "ecai_output",
        substitution: dict[str, Any] | None = None,
    ) -> ConverseResult:
        occupant = self._occupant(role, persona)
        self.manifest.assert_declared(occupant.model_id)
        schema = resolved_schema(schema_name)
        tool_config = self._tool_config(schema, tool_name)

        attempt = 0
        total_retries = 0
        last_error: str | None = None
        last_response: Any = None
        last_latency = 0

        while attempt <= self.manifest.parse_retries:
            user_text = user
            if last_error is not None:
                user_text = (
                    f"{user}\n\nPREVIOUS ATTEMPT FAILED VALIDATION: {last_error}\n"
                    "Return corrected JSON only."
                )
            messages = [{"role": "user", "content": [{"text": user_text}]}]
            request = {
                "modelId": occupant.model_id,
                "system": [{"text": system}],
                "messages": messages,
                "toolConfig": tool_config,
                "inferenceConfig": self.inference,
            }

            started = time.perf_counter()
            try:
                response, retries = call_with_retries(
                    lambda: self._client.converse(
                        modelId=request["modelId"],
                        system=request["system"],
                        messages=request["messages"],
                        toolConfig=request["toolConfig"],
                        inferenceConfig=request["inferenceConfig"],
                    ),
                    self.policy,
                    sleep=self._sleep,
                )
            except ModelTimeoutError as exc:
                last_latency = int((time.perf_counter() - started) * 1000)
                self._record(
                    role=role, persona=persona, occupant=occupant, request=request,
                    response=None, latency_ms=last_latency, retries=0,
                    parse_retries=attempt, valid=False, error="TIMEOUT",
                    substitution=substitution,
                )
                return ConverseResult(
                    valid=False, parsed=None, raw=None, role=role, persona=persona,
                    model_id=occupant.model_id, latency_ms=last_latency, retries=0,
                    parse_retries=attempt, error="TIMEOUT",
                )
            except ModelInvocationError as exc:
                last_latency = int((time.perf_counter() - started) * 1000)
                self._record(
                    role=role, persona=persona, occupant=occupant, request=request,
                    response=None, latency_ms=last_latency, retries=0,
                    parse_retries=attempt, valid=False, error=f"INVOCATION_FAILED: {exc}",
                    substitution=substitution,
                )
                return ConverseResult(
                    valid=False, parsed=None, raw=None, role=role, persona=persona,
                    model_id=occupant.model_id, latency_ms=last_latency, retries=0,
                    parse_retries=attempt, error=f"INVOCATION_FAILED: {exc}",
                )

            last_latency = int((time.perf_counter() - started) * 1000)
            total_retries += retries
            last_response = response

            # raw retention BEFORE parsing (P20 §5.2)
            if self.raw is not None:
                self.raw.store(
                    stage=schema_name.split("/")[1],
                    persona=persona,
                    model_id=occupant.model_id,
                    request=request,
                    response=response,
                    latency_ms=last_latency,
                    retries=total_retries,
                )

            parsed, error = self._extract(response, schema_name)
            if parsed is not None:
                self._record(
                    role=role, persona=persona, occupant=occupant, request=request,
                    response=response, latency_ms=last_latency, retries=total_retries,
                    parse_retries=attempt, valid=True, error=None,
                    substitution=substitution,
                )
                return ConverseResult(
                    valid=True, parsed=parsed, raw=response, role=role, persona=persona,
                    model_id=occupant.model_id, latency_ms=last_latency,
                    retries=total_retries, parse_retries=attempt, error=None,
                )

            last_error = error
            attempt += 1

        self._record(
            role=role, persona=persona, occupant=occupant,
            request={"modelId": occupant.model_id, "schema_name": schema_name},
            response=last_response, latency_ms=last_latency, retries=total_retries,
            parse_retries=attempt, valid=False, error=last_error,
            substitution=substitution,
        )
        return ConverseResult(
            valid=False, parsed=None, raw=last_response, role=role, persona=persona,
            model_id=occupant.model_id, latency_ms=last_latency, retries=total_retries,
            parse_retries=attempt, error=last_error,
        )

    @staticmethod
    def _extract(
        response: Any, schema_name: str
    ) -> tuple[dict[str, Any] | None, str | None]:
        if not isinstance(response, dict):
            return None, "non-dict response envelope"
        content = (
            response.get("output", {}).get("message", {}).get("content")
            if isinstance(response.get("output"), dict)
            else None
        )
        if not isinstance(content, list):
            return None, "missing output.message.content"
        for block in content:
            tool_use = block.get("toolUse") if isinstance(block, dict) else None
            if tool_use:
                candidate = tool_use.get("input")
                try:
                    validate(candidate, schema_name)
                except SchemaValidationError as exc:
                    return None, "schema validation failed: " + "; ".join(exc.errors[:3])
                return candidate, None
        return None, "no toolUse block in response"

    # ------------------------------------------------------------------ gatekeeper
    def invoke_gatekeeper(
        self,
        *,
        request: dict[str, Any],
        schema_name: str = "ecai/gatekeeper_response/1.0",
        run_id: str | None = None,
        system: str = (
            "You are the ECAI Gatekeeper. Validate the curated item against the rules. "
            "You may not modify the pick, selection, or any numeric value. Return exactly "
            "one verdict: CONFIRM, CHALLENGE, FLAG, ESCALATE, or KILL."
        ),
        substitution: dict[str, Any] | None = None,
    ) -> GatekeeperOutcome:
        result = self.converse_structured(
            role="gatekeeper",
            persona=None,
            system=system,
            user=json.dumps(request, ensure_ascii=True),
            schema_name=schema_name,
            tool_name="gatekeeper_response",
            substitution=substitution,
        )
        if result.valid:
            return GatekeeperOutcome(ok=True, response=result.parsed, stop=None)

        game_key = (
            request.get("curated_item", {}).get("inline", {}).get("game_key")
            if isinstance(request.get("curated_item"), dict)
            else None
        )
        stop = {
            "schema_id": "ecai/run_stop/1.0",
            "status": GATEKEEPER_UNAVAILABLE,
            "run_id": run_id,
            "game_key": game_key,
            "model_id": result.model_id,
            "reason": result.error,
        }
        if self.provenance is not None:
            self.provenance.append({"kind": "run_stop", **stop})
        return GatekeeperOutcome(ok=False, response=None, stop=stop)
