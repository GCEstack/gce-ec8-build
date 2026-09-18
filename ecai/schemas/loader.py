"""Schema loader + fail-closed validator for the ECAI contracts (WS1).

Every stage boundary validates its emitted artifact against the contract schema
and fails closed (raises) on violation. Cross-file `$ref`s (e.g. an
`analyst_verdict.rationale` item referencing `ecai/evidence_item/1.0`) resolve
through a `referencing` registry built from the schema directory.
"""

from __future__ import annotations

import copy
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_DIR: Path = Path(__file__).resolve().parent

# Cross-file references use the P20 logical id form, e.g. "ecai/evidence_item/1.0".
_CROSS_REF_RE = re.compile(r"^ecai/([a-z_]+)/1\.0$")

ENVELOPE_SCHEMA_ID = "ecai/common_envelope/1.0"

# The ten contract schemas (P20 §2.1–§2.9; §2.8 is the request/response pair).
CONTRACTS: tuple[str, ...] = (
    "binding_record",
    "framing_object",
    "evidence_item",
    "det_output",
    "analyst_verdict",
    "convergence_result",
    "curated_slate_item",
    "gatekeeper_request",
    "gatekeeper_response",
    "terminal_item",
)


class SchemaValidationError(ValueError):
    """Raised when an artifact fails its contract schema (fail-closed)."""

    def __init__(self, schema_name: str, errors: list[str]):
        self.schema_name = schema_name
        self.errors = errors
        super().__init__(
            f"schema validation failed for {schema_name}: " + "; ".join(errors)
        )


@lru_cache(maxsize=None)
def _schema_files() -> tuple[Path, ...]:
    return tuple(sorted(SCHEMA_DIR.glob("*.json")))


@lru_cache(maxsize=None)
def _raw_schemas() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for path in _schema_files():
        schema = json.loads(path.read_text(encoding="utf-8"))
        out[path.stem] = schema
    return out


def _resolve_key(name: str) -> str:
    """Accept a file stem ('binding_record') or a schema id ('ecai/.../1.0')."""
    if name in _raw_schemas():
        return name
    if name == ENVELOPE_SCHEMA_ID:
        return "common_envelope"
    for stem, schema in _raw_schemas().items():
        if schema.get("$id") == name:
            return stem
    raise KeyError(f"unknown schema: {name}")


@lru_cache(maxsize=None)
def _schema_body(name: str) -> dict[str, Any]:
    """A schema body stripped of `$id`/`$schema`, suitable for a `$defs` entry."""
    body = copy.deepcopy(_raw_schemas()[_resolve_key(name)])
    body.pop("$id", None)
    body.pop("$schema", None)
    return body


def _collect_cross_refs(node: Any, out: list[str]) -> None:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            match = _CROSS_REF_RE.match(ref)
            if match and match.group(1) not in out:
                out.append(match.group(1))
        for value in node.values():
            _collect_cross_refs(value, out)
    elif isinstance(node, list):
        for value in node:
            _collect_cross_refs(value, out)


def _localize_refs(node: Any) -> None:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            match = _CROSS_REF_RE.match(ref)
            if match:
                node["$ref"] = f"#/$defs/{match.group(1)}"
        for value in node.values():
            _localize_refs(value)
    elif isinstance(node, list):
        for value in node:
            _localize_refs(value)


@lru_cache(maxsize=None)
def resolved_schema(name: str) -> dict[str, Any]:
    """Return a self-contained schema with cross-file refs inlined into `$defs`.

    The on-disk contracts keep the P20 `$id: ecai/<name>/1.0` form and logical
    cross-refs; the loader rewrites those refs to local `#/$defs/<name>` so the
    schema validates with a stock Draft 2020-12 validator and no retrieval layer.
    """
    root = copy.deepcopy(_raw_schemas()[_resolve_key(name)])
    root.pop("$id", None)

    needed: list[str] = []
    _collect_cross_refs(root, needed)
    index = 0
    while index < len(needed):
        body = _schema_body(needed[index])
        index += 1
        _collect_cross_refs(body, needed)

    defs: dict[str, Any] = {name: _schema_body(name) for name in needed}
    for body in defs.values():
        _localize_refs(body)
    _localize_refs(root)
    if defs:
        existing = root.setdefault("$defs", {})
        existing.update(defs)
    return root


@lru_cache(maxsize=None)
def _validator_for(name: str) -> Draft202012Validator:
    schema = resolved_schema(name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def schema_names() -> tuple[str, ...]:
    """All schema file stems, sorted."""
    return tuple(sorted(_raw_schemas()))


def load_schema(name: str) -> dict[str, Any]:
    """Return the raw schema dict for a stem or schema id."""
    return _raw_schemas()[_resolve_key(name)]


def validate(instance: Any, schema_name: str) -> None:
    """Validate `instance` against `schema_name`; raise SchemaValidationError on failure."""
    validator = _validator_for(schema_name)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
    if errors:
        raise SchemaValidationError(schema_name, [_format_error(e) for e in errors])


def validate_envelope(instance: Any) -> None:
    """Validate only the common envelope fields of an artifact."""
    validate(instance, ENVELOPE_SCHEMA_ID)


def _format_error(error: Any) -> str:
    path = "/".join(str(p) for p in error.absolute_path) or "<root>"
    return f"{path}: {error.message}"
