"""VL/NO adapter shells — wire-contract shape, fail closed on unpinned enums.

VL wire record: {layer, state, failure_class?, test_id?, detail}. layer/state carry only
structurally closed values; failure_class and test_id are FC-enum v1.0 surfaces whose
VALUE space is unpinned (Kimi owns semantics, Chiave owns the wire contract) — any
supplied value is rejected, never defaulted or silently passed. NO wire: the normalizer
input contract is exactly {self-assessment, sufficiency, validation state, validation
flags}; a fifth input (Pass override / peer output / selection) is rejected and
`Contradicted` is never accepted from a caller (system-assignable only, NO-6).

L2/L3 adapters are shells that may carry a bound provider; any provider execution they
trigger flows through the W1 execution point (Provider.execute) so metering is
no-retrofit into Wave 2 construction (W2-C8). L1 and NO never touch a model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ._stubs import VALIDATION_STATES, UnpinnedSemanticError

VALIDATION_LAYERS = ("L1", "L2", "L3")
NO_REQUIRED_INPUTS = ("self_assessment", "sufficiency", "validation_state", "validation_flags")


@dataclass
class ValidationAdapter:
    """A validation-layer shell (VL-1..4 wire contract). Fails closed on unpinned enums."""

    layer: str
    provider: Any = None
    allowed_states: tuple[str, ...] = VALIDATION_STATES

    def __post_init__(self):
        if self.layer not in VALIDATION_LAYERS:
            raise ValueError(f"unknown validation layer {self.layer}")

    def bind_provider(self, provider: Any) -> None:
        self.provider = provider

    def run(self, record: dict[str, Any]) -> dict[str, Any]:
        violations: list[str] = []
        if record.get("layer") != self.layer:
            violations.append(f"layer mismatch: record={record.get('layer')} adapter={self.layer}")
        state = record.get("state")
        if not isinstance(state, str) or state not in self.allowed_states:
            violations.append(f"state outside closed set: {state!r}")
        extra = set(record) - {"layer", "state", "failure_class", "test_id", "detail"}
        if extra:
            violations.append(f"unexpected wire keys: {sorted(extra)}")
        if record.get("failure_class") is not None:
            raise UnpinnedSemanticError("failure_class value supplied but FC enum v1.0 is unpinned (Kimi); fail closed")
        if record.get("test_id") is not None:
            raise UnpinnedSemanticError("test_id value supplied but test space is unpinned (Kimi); fail closed")
        if violations:
            return {"ok": False, "violations": violations}
        return {
            "ok": True,
            "wire": {"layer": self.layer, "state": state, "failure_class": None, "test_id": None, "detail": record.get("detail")},
        }

    def submit_execution(self, provider_call: Any) -> dict[str, Any]:
        """Any provider execution this adapter triggers flows through the execution point."""
        if self.provider is None:
            raise UnpinnedSemanticError("adapter not bound to a provider; refusing implicit execution")
        return self.provider.execute(provider_call)


class NormalizerAdapter:
    """NO-stack shell. Exact four-component input contract; deterministic only (NO-5)."""

    def __init__(self, version: str = "1.0"):
        self.version = version

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        violations: list[str] = []
        for req in NO_REQUIRED_INPUTS:
            if req not in inputs:
                violations.append(f"missing normalizer input {req}")
        extra = set(inputs) - set(NO_REQUIRED_INPUTS)
        if extra:
            raise UnpinnedSemanticError(
                f"fifth/further normalizer input present {sorted(extra)}; Pass-override / extra-input semantics "
                "are a Kimi-held surface — fail closed"
            )
        if inputs.get("validation_state") == "contradicted":
            raise UnpinnedSemanticError("Contradicted is system-assignable only (NO-6); caller value rejected, fail closed")
        if violations:
            return {"ok": False, "violations": violations}
        return {
            "ok": True,
            "non_collapsed": {k: inputs[k] for k in NO_REQUIRED_INPUTS},
            "note": "shape accepted; sufficiency FORMULA (D13) is a Kimi-held surface and is not computed here",
            "model_called": False,
        }
