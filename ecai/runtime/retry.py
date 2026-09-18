"""WS4 — retry / timeout policy (P20 §5.2).

Retries apply to throttling and 5xx responses with manifest backoff. A timeout is
terminal-invalid (it counts as invalid for quorum, per §5.2) — it is not retried.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

# Retryable error codes (throttling / transient service failures).
THROTTLE_CODES: frozenset[str] = frozenset(
    {
        "Throttling",
        "ThrottlingException",
        "TooManyRequestsException",
        "RequestLimitExceeded",
        "ServiceUnavailable",
        "ServiceUnavailableException",
        "InternalServerException",
        "ModelNotReadyException",
    }
)

# Terminal (never retried) error codes.
TERMINAL_CODES: frozenset[str] = frozenset(
    {
        "ValidationException",
        "AccessDeniedException",
        "ResourceNotFoundException",
        "ModelErrorException",
        "ModelTimeoutException",
        "ModelStreamErrorException",
    }
)


class ModelInvocationError(RuntimeError):
    """Persistent invocation failure after retries (invalid for quorum)."""


class ModelTimeoutError(ModelInvocationError):
    """A timeout — terminal-invalid, counts as invalid for quorum (§5.2)."""


@dataclass(frozen=True)
class RetryPolicy:
    timeout_s: int
    max_retries: int
    backoff_s: tuple[int, ...]

    def backoff_for(self, attempt: int) -> int:
        if not self.backoff_s:
            return 0
        return self.backoff_s[min(attempt, len(self.backoff_s) - 1)]


def is_timeout(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError,)):
        return True
    name = type(exc).__name__
    return "Timeout" in name


def is_retryable(exc: BaseException) -> bool:
    if is_timeout(exc):
        return False
    name = type(exc).__name__
    if name in TERMINAL_CODES:
        return False
    if name in THROTTLE_CODES:
        return True
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = str(response.get("Error", {}).get("Code", ""))
        if code in TERMINAL_CODES:
            return False
        if code in THROTTLE_CODES:
            return True
        status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if isinstance(status, int) and status >= 500:
            return True
    return False


def call_with_retries(
    fn: Callable[[], Any],
    policy: RetryPolicy,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[Any, int]:
    """Call `fn`, retrying throttling/5xx with backoff. Returns `(result, retries)`."""
    retries = 0
    while True:
        try:
            return fn(), retries
        except BaseException as exc:  # noqa: BLE001 - classified below
            if is_timeout(exc):
                raise ModelTimeoutError(str(exc)) from exc
            if not is_retryable(exc) or retries >= policy.max_retries:
                raise ModelInvocationError(
                    f"invocation failed after {retries} retries: {type(exc).__name__}: {exc}"
                ) from exc
            sleep(policy.backoff_for(retries))
            retries += 1
