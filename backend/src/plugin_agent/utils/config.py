from __future__ import annotations

from typing import Any


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _join_config_path(prefix: str, key: str) -> str:
    return f"{prefix}.{key}" if prefix else key


def _encrypted_path_matches(path: str, encrypted_paths: set[str]) -> bool:
    path_parts = path.split(".") if path else []
    for encrypted_path in encrypted_paths:
        encrypted_parts = encrypted_path.split(".") if encrypted_path else []
        if len(path_parts) != len(encrypted_parts):
            continue
        if all(expected == "*" or expected == actual for expected, actual in zip(encrypted_parts, path_parts)):
            return True
    return False


def collect_encrypted_paths(schema: dict[str, Any], prefix: str = "") -> set[str]:
    encrypted: set[str] = set()
    if schema.get("x-encrypted") is True or schema.get("x-secret") is True:
        if prefix:
            encrypted.add(prefix)
    for key, child in (schema.get("properties") or {}).items():
        if isinstance(child, dict):
            path = _join_config_path(prefix, key)
            encrypted.update(collect_encrypted_paths(child, path))
    additional_properties = schema.get("additionalProperties")
    if isinstance(additional_properties, dict):
        encrypted.update(collect_encrypted_paths(additional_properties, _join_config_path(prefix, "*")))
    items = schema.get("items")
    if isinstance(items, dict):
        encrypted.update(collect_encrypted_paths(items, _join_config_path(prefix, "*")))
    for variant_key in ("allOf", "anyOf", "oneOf"):
        for variant in schema.get(variant_key) or []:
            if isinstance(variant, dict):
                encrypted.update(collect_encrypted_paths(variant, prefix))
    return encrypted


def redact_config(config: Any, encrypted_paths: set[str], prefix: str = "") -> Any:
    if isinstance(config, dict):
        redacted = {}
        for key, value in config.items():
            path = _join_config_path(prefix, str(key))
            if isinstance(value, (dict, list)):
                redacted[key] = redact_config(value, encrypted_paths, path)
            elif _encrypted_path_matches(path, encrypted_paths):
                redacted[key] = "********" if value else None
            else:
                redacted[key] = value
        return redacted
    if isinstance(config, list):
        return [redact_config(value, encrypted_paths, _join_config_path(prefix, str(index))) for index, value in enumerate(config)]
    if _encrypted_path_matches(prefix, encrypted_paths):
        return "********" if config else None
    return config
