"""WS5 — binding adapter package (P20 §1, §6)."""

from .adapter import bind  # noqa: F401
from .models import (  # noqa: F401
    BINDING_SCHEMA_VERSION,
    REJECTION_REASONS,
    REQUIRED_ARTIFACTS,
    BindingRecord,
    BindingRejected,
    ManifestEntry,
)

__all__ = [
    "bind",
    "BindingRecord",
    "BindingRejected",
    "ManifestEntry",
    "BINDING_SCHEMA_VERSION",
    "REJECTION_REASONS",
    "REQUIRED_ARTIFACTS",
]
