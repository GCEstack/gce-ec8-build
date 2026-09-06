"""Provider abstraction + MockProvider (brief §5 criteria 1-3, A0 OB-3 / I10).

Design intent — NO-RETROFIT meter (OB-3): every provider call flows through the single
execution point `Provider.execute()`. Metering into the ledger and observability emission
happen INSIDE that execution point, in the provider layer itself — never in the calling
(orchestration) layer. A caller that invokes `execute()` automatically meters; a caller that
skips the ledger still gets rows because metering is intrinsic to the provider boundary.

Ledger semantics: each ATTEMPT is one ledger row. A retry is an EXTRA row. A terminal
failure is its own row. Token counts are recorded per attempt (OB-1: request + tokens).
This is the "retries/failures are extra ledger rows" property.
"""

from __future__ import annotations

import time
import json
from abc import ABC, abstractmethod
from typing import Any, Callable

from .ledger import Ledger


class ProviderCall:
    """A single logical provider call descriptor at the execution point."""

    def __init__(
        self,
        model_id: str,
        component: str,
        run_id: str,
        layer: str,
        source: str,
        analyst_slot: str | None = None,
        prompt: str = "",
        max_attempts: int = 1,
        request_meta: dict[str, Any] | None = None,
    ):
        self.model_id = model_id
        self.component = component
        self.run_id = run_id
        self.layer = layer
        self.source = source
        self.analyst_slot = analyst_slot
        self.prompt = prompt
        self.max_attempts = max_attempts
        self.request_meta = request_meta or {}

    def to_row(self, attempt: int, outcome: str, token_counts: dict[str, int], duration_ms: float) -> dict[str, Any]:
        return {
            "kind": "provider_call",
            "model_id": self.model_id,
            "component": self.component,
            "run_id": self.run_id,
            "layer": self.layer,
            "source": self.source,
            "analyst_slot": self.analyst_slot,
            "attempt": attempt,
            "outcome": outcome,  # ok | retry | failed
            "prompt_tokens": token_counts.get("prompt_tokens", 0),
            "completion_tokens": token_counts.get("completion_tokens", 0),
            "total_tokens": token_counts.get("total_tokens", 0),
            "duration_ms": round(duration_ms, 3),
            **self.request_meta,
        }


class Provider(ABC):
    """Base provider abstraction. Subclasses implement `_transmit` (the model-boundary
    round trip). Metering/emission are handled by `execute` (the single execution point)
    so they can never be skipped or retrofitted by callers (OB-3)."""

    def __init__(
        self,
        ledger: Ledger,
        on_emit: Callable[[dict[str, Any]], None] | None = None,
        backoff_seconds: tuple[float, ...] = (0.0, 0.0),
    ):
        self._ledger = ledger
        self._on_emit = on_emit or (lambda _ev: None)
        self._backoff = backoff_seconds

    # ---- single execution point (meter + emit live here) ----
    def execute(self, call: ProviderCall) -> dict[str, Any]:
        """THE execution point through which every provider call flows.

        Meters every attempt into the ledger and emits observability, at the provider
        boundary. Retries/failures append extra ledger rows. Callers cannot bypass this.
        """
        last_error: Exception | None = None
        for attempt in range(1, call.max_attempts + 1):
            counts = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            start = time.perf_counter()
            try:
                result = self._transmit(call)
                counts = result["token_counts"]
                duration = (time.perf_counter() - start) * 1000.0
                row = call.to_row(attempt, "ok", counts, duration)
                self._ledger.append_row(row)
                self._emit(call, attempt, "ok", counts, duration)
                return {"status": "ok", "ledger_row": row, "model_id": call.model_id, "content": result.get("content")}
            except TransientError as e:
                last_error = e
                counts = e.token_counts
                duration = (time.perf_counter() - start) * 1000.0
                if attempt < call.max_attempts:
                    # this attempt was transient and WILL be retried -> one 'retry' row
                    row = call.to_row(attempt, "retry", counts, duration)
                    self._ledger.append_row(row)
                    self._emit(call, attempt, "retry", counts, duration)
                    delay = self._backoff[min(attempt - 1, len(self._backoff) - 1)] if self._backoff else 0.0
                    if delay:
                        time.sleep(delay)
                    continue
                # no attempts left -> terminal failure as its own row
                row = call.to_row(attempt, "failed", counts, duration)
                self._ledger.append_row(row)
                self._emit(call, attempt, "failed", counts, duration)
                return {"status": "failed", "reason": str(e), "ledger_row": row}
            except Exception as e:  # non-transient (auth/schema/etc): no retry, terminal failed
                last_error = e
                duration = (time.perf_counter() - start) * 1000.0
                row = call.to_row(attempt, "failed", counts, duration)
                self._ledger.append_row(row)
                self._emit(call, attempt, "failed", counts, duration)
                return {"status": "failed", "reason": str(e), "ledger_row": row}
        return {"status": "failed", "reason": str(last_error) if last_error else "unknown"}

    # ---- provider-boundary hook ----
    @abstractmethod
    def _transmit(self, call: ProviderCall) -> dict[str, Any]:
        """Perform the model-boundary round trip. Return dict with 'content' + 'token_counts'."""

    # ---- observability emit (OB-2 granularity) ----
    def _emit(self, call: ProviderCall, attempt: int, outcome: str, counts: dict[str, int], duration_ms: float) -> None:
        self._on_emit(
            {
                "event": "provider_call",
                "component": call.component,
                "run_id": call.run_id,
                "layer": call.layer,
                "source": call.source,
                "analyst_slot": call.analyst_slot,
                "model_id": call.model_id,
                "attempt": attempt,
                "outcome": outcome,
                "prompt_tokens": counts["prompt_tokens"],
                "completion_tokens": counts["completion_tokens"],
                "total_tokens": counts["total_tokens"],
                "duration_ms": round(duration_ms, 3),
            }
        )


class TransientError(Exception):
    """Transient failure (retryable: e.g. simulated 429/5xx). Carries token counts."""

    def __init__(self, message: str, token_counts: dict[str, int]):
        super().__init__(message)
        self.token_counts = token_counts


class MockProvider(Provider):
    """In-process mock provider. No network, no live spend ($0). Simulates deterministic
    token counts and can be programmed to fail transiently or terminally."""

    def __init__(self, ledger: Ledger, on_emit=None, backoff_seconds=(0.0, 0.0)):
        super().__init__(ledger, on_emit=on_emit, backoff_seconds=backoff_seconds)
        self._force_transient: dict[int, int] = {}  # call_point -> remaining transient failures
        self._force_terminal: set[int] = set()  # call_point -> terminal failure

    def program_transient(self, call_point: int, times: int = 1) -> None:
        self._force_transient[call_point] = times

    def program_terminal(self, call_point: int) -> None:
        self._force_terminal.add(call_point)

    def _transmit(self, call: ProviderCall) -> dict[str, Any]:
        cp = call.request_meta.get("call_point")
        if cp in self._force_terminal:
            raise RuntimeError(f"simulated terminal (non-retryable) failure at call_point {cp}")
        counts = self._mock_tokens(call)
        if self._force_transient.get(cp, 0) > 0:
            self._force_transient[cp] -= 1
            raise TransientError(f"simulated transient failure at call_point {cp}", counts)
        content = {"model_id": call.model_id, "echo": call.prompt[:40]}
        return {"content": content, "token_counts": counts}

    @staticmethod
    def _mock_tokens(call: ProviderCall) -> dict[str, int]:
        prompt_tokens = 100 + (hash(call.model_id) % 200) + (len(call.prompt) // 4)
        completion_tokens = 20 + (hash(call.component) % 180)
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }
