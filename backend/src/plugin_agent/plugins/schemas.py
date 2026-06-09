from __future__ import annotations

from typing import Any


def object_schema(properties: dict[str, Any], required: list[str] | None = None, additional: bool = False) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": additional,
    }


def ok_schema(properties: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    return object_schema(properties or {}, required or [], additional=False)
