"""Shared primitives for versioned, immutable boundary contracts."""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

SCHEMA_VERSION = "0.1"


class ContractValidationError(ValueError):
    """Raised when data violates a public component-boundary contract."""


def require_id(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field_name} must be a non-empty string")


def require_schema(value: str) -> None:
    if value != SCHEMA_VERSION:
        raise ContractValidationError(
            f"unsupported schema_version {value!r}; expected {SCHEMA_VERSION!r}"
        )


def require_json_value(value: Any, field_name: str = "value") -> None:
    try:
        json.dumps(value)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"{field_name} must be JSON-serializable") from exc


def frozen_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    require_json_value(dict(value), "mapping")
    if any(not isinstance(key, str) for key in value):
        raise ContractValidationError("mapping keys must be strings")
    return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ContractValidationError("mapping keys must be strings")
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze_json(item) for item in value)
    return value


def to_primitive(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {field.name: to_primitive(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): to_primitive(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [to_primitive(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(to_primitive(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def parse_json(payload: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ContractValidationError("payload is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ContractValidationError("top-level JSON value must be an object")
    return value

