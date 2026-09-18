"""WS5 — source-only framing package (P20 §2.2, §3.1)."""

from .framer import (  # noqa: F401
    FACTOR_SPECS,
    FramingError,
    build_framing_object,
    frame_slate,
    load_markets_config,
    scope_config,
    slugify,
    split_game_key,
)
from .redaction import (  # noqa: F401
    FACTOR_WHITELIST,
    FORBIDDEN_SOURCE_TOKENS,
    RedactionViolation,
    assert_source_allowed,
)

__all__ = [
    "frame_slate",
    "build_framing_object",
    "load_markets_config",
    "scope_config",
    "split_game_key",
    "slugify",
    "FACTOR_SPECS",
    "FramingError",
    "FACTOR_WHITELIST",
    "FORBIDDEN_SOURCE_TOKENS",
    "RedactionViolation",
    "assert_source_allowed",
]
