"""MockCatalog — local, GET /v1/models-like provider catalog (brief §5 criterion 6).

Behaves like a `GET /v1/models` contract locally WITHOUT contacting any live gateway and
WITHOUT asserting that any model id exists on Mantle. Entries are FIXTURE data (from the
Profile-V-style roster in Calibro readiness §E, treated as non-approved fixture strings per
RQ-14 / brief authority). No live pin. RQ-14 remains unsatisfied by design.
"""

from __future__ import annotations

from typing import Any

# Fixture roster (NON-approved). Keys = mantle-style model id; values = fixture metadata.
# Deliberately mirrors readiness §E shape but carries NO approval claim and NO live pin.
MOCK_MODELS: dict[str, dict[str, Any]] = {
    "qwen.qwen3-32b-v1:0": {"family_id": "qwen", "role_hint": "framing"},
    "qwen.qwen3-235b-a22b-2507-v1:0": {"family_id": "qwen", "role_hint": "analyst"},
    "deepseek.v3.2": {"family_id": "deepseek", "role_hint": "analyst"},
    "moonshotai.kimi-k2.5": {"family_id": "kimi", "role_hint": "analyst"},
    "zai.glm-5": {"family_id": "glm", "role_hint": "analyst"},
    "mistral.mistral-large-3-675b-instruct": {"family_id": "mistral", "role_hint": "l3"},
    "anthropic.claude-haiku-4-5-20251001-v1:0": {"family_id": "claude", "role_hint": "l3_fallback"},
}


class MockCatalog:
    """Local models catalog that behaves like the models-list contract."""

    def __init__(self, models: dict[str, dict[str, Any]] | None = None):
        self._models = dict(models) if models is not None else dict(MOCK_MODELS)

    def list_models(self) -> list[dict[str, Any]]:
        """Equivalent of `GET /v1/models` locally: returns fixture entries (no live call)."""
        return [
            {"model_id": mid, "family_id": meta.get("family_id"), "role_hint": meta.get("role_hint")}
            for mid, meta in sorted(self._models.items())
        ]

    def has(self, model_id: str) -> bool:
        return model_id in self._models

    def get(self, model_id: str) -> dict[str, Any]:
        meta = self._models.get(model_id)
        if meta is None:
            raise KeyError(f"model not in mock catalog: {model_id}")
        return {"model_id": model_id, **meta}
