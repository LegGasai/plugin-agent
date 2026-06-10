from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from packaging.version import InvalidVersion, Version


def version_sort_key(version: str) -> tuple[int, Any]:
    try:
        return (1, Version(str(version)))
    except InvalidVersion:
        return (0, str(version))


def latest_version(versions: list[str]) -> str:
    return max((str(version) for version in versions), key=version_sort_key)


def select_default_package(packages: list[dict[str, Any]]) -> dict[str, Any]:
    installed_packages = [package for package in packages if package.get("source") == "installed"]
    if installed_packages:
        return max(installed_packages, key=installed_activity_sort_key)
    return max(
        packages,
        key=lambda package: (
            version_sort_key(str(package.get("version", "1.0.0"))),
            1 if package.get("source") == "installed" else 0,
        ),
    )


def installed_activity_sort_key(package: dict[str, Any]) -> tuple[float, tuple[int, Any]]:
    updated_at = package.get("updated_at")
    if isinstance(updated_at, str):
        try:
            return (datetime.fromisoformat(updated_at).timestamp(), version_sort_key(str(package.get("version", "1.0.0"))))
        except ValueError:
            pass
    installed_path = package.get("installed_path")
    if installed_path:
        try:
            return (Path(installed_path).stat().st_mtime, version_sort_key(str(package.get("version", "1.0.0"))))
        except OSError:
            pass
    return (0.0, version_sort_key(str(package.get("version", "1.0.0"))))
