"""WS4 — Bedrock runtime core package (P20 §5)."""

from .bedrock_client import (  # noqa: F401
    GATEKEEPER_UNAVAILABLE,
    BedrockConverseClient,
    ConverseResult,
    GatekeeperOutcome,
)
from .manifest import (  # noqa: F401
    QUORUM_OK,
    QUORUM_STOP,
    ManifestError,
    Occupant,
    RuntimeManifest,
    UndeclaredModelError,
    diff_substitutions,
    evaluate_quorum,
    load_manifest,
    quorum_decision,
    quorum_requirement,
)
from .provenance import ProvenanceLog, RawRetention  # noqa: F401
from .retry import (  # noqa: F401
    ModelInvocationError,
    ModelTimeoutError,
    RetryPolicy,
    call_with_retries,
    is_retryable,
    is_timeout,
)

__all__ = [
    "load_manifest",
    "RuntimeManifest",
    "Occupant",
    "ManifestError",
    "UndeclaredModelError",
    "diff_substitutions",
    "quorum_requirement",
    "evaluate_quorum",
    "quorum_decision",
    "QUORUM_OK",
    "QUORUM_STOP",
    "RetryPolicy",
    "call_with_retries",
    "is_retryable",
    "is_timeout",
    "ModelInvocationError",
    "ModelTimeoutError",
    "ProvenanceLog",
    "RawRetention",
    "BedrockConverseClient",
    "ConverseResult",
    "GatekeeperOutcome",
    "GATEKEEPER_UNAVAILABLE",
]
