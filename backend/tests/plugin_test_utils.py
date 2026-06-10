from __future__ import annotations

from pathlib import Path

from plugin_agent.plugin_store import load_installed_plugin_class, package_from_path

MARKET_DIR = Path(__file__).resolve().parents[2] / "plugin-market"


def market_plugin_class(package_dir_name: str):
    package_path = MARKET_DIR / package_dir_name
    package = package_from_path(package_path, source="market", package_path=str(package_path))
    return load_installed_plugin_class(package_path, package.entrypoint)
