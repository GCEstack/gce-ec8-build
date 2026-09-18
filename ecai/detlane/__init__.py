"""WS2 — deterministic lane package (P20 §2.4)."""

from .lane import (  # noqa: F401
    DetError,
    compute_sufficiency,
    load_det_config,
    run_det,
    run_det_slate,
)

__all__ = [
    "run_det",
    "run_det_slate",
    "compute_sufficiency",
    "load_det_config",
    "DetError",
]
