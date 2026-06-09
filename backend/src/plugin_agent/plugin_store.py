from __future__ import annotations

import importlib.util
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any

import yaml

from plugin_agent_sdk import Plugin as PluginBase
from plugin_agent_sdk.contracts import PluginPackage, ResourceSpec, RuntimeSpec, SchemaDefinition


PLUGIN_PACKAGE_EXTENSION = ".pluginpkg"


def safe_package_dir_name(package_id: str) -> str:
    return package_id.replace("/", "__").replace("\\", "__")


def read_plugin_manifest(path: str | Path) -> tuple[dict[str, Any], str]:
    plugin_path = Path(path).expanduser()
    if plugin_path.is_dir():
        manifest_path = plugin_path / "plugin.yaml"
        if not manifest_path.exists():
            raise ValueError("plugin.yaml is required")
        return _read_yaml(manifest_path), str(manifest_path)
    if not plugin_path.exists():
        raise ValueError(f"plugin package does not exist: {plugin_path}")
    with zipfile.ZipFile(plugin_path) as archive:
        if "plugin.yaml" not in archive.namelist():
            raise ValueError("plugin.yaml is required")
        with archive.open("plugin.yaml") as handle:
            data = yaml.safe_load(handle.read().decode("utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("plugin.yaml must contain a YAML object")
    return data, f"{plugin_path}!plugin.yaml"


def package_from_path(path: str | Path, source: str, package_path: str | None = None) -> PluginPackage:
    manifest, manifest_path = read_plugin_manifest(path)
    package = package_from_manifest(manifest, manifest_path, source)
    if source == "market":
        package.market_path = package_path or str(Path(path).expanduser())
    elif source == "installed":
        package.installed_path = package_path or str(Path(path).expanduser())
    return package


def package_from_manifest(manifest: dict[str, Any], manifest_path: str, source: str) -> PluginPackage:
    descriptor = _descriptor_from_manifest(manifest)
    runtime = RuntimeSpec.model_validate(manifest.get("runtime", {}) or {})
    return PluginPackage(
        package_id=descriptor["id"],
        name=descriptor.get("name") or descriptor["id"],
        version=str(descriptor.get("version", "1.0.0")),
        entrypoint=runtime.entrypoint,
        runtime=runtime,
        manifest_path=manifest_path,
        source=source,
        author=descriptor.get("author"),
        description=descriptor.get("description") or "",
        categories=descriptor.get("categories", []),
        tags=descriptor.get("tags", []),
        provides=descriptor.get("provides", []),
        requires=descriptor.get("requires", []),
        resources=[ResourceSpec.model_validate(resource) for resource in manifest.get("resources", [])],
        config_schema_ref=descriptor.get("config_schema_ref"),
        schemas=[SchemaDefinition.model_validate(schema) for schema in manifest.get("schemas", [])],
    )


def validate_plugin_package(path: str | Path) -> dict[str, Any]:
    errors: list[str] = []
    try:
        package = package_from_path(path, source="market")
        if package.runtime.type != "python.in_process":
            errors.append("only python.in_process runtime is supported")
        if not package.runtime.entrypoint:
            errors.append("runtime.entrypoint is required")
    except Exception as exc:
        return {"valid": False, "errors": [str(exc)]}
    return {"valid": not errors, "errors": errors, "plugin_package": package.model_dump()}


def copy_package_to_market(path: str | Path, market_dir: Path) -> tuple[PluginPackage, Path]:
    validation = validate_plugin_package(path)
    if not validation["valid"]:
        raise ValueError("; ".join(validation["errors"]))
    package = PluginPackage.model_validate(validation["plugin_package"])
    market_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{safe_package_dir_name(package.package_id)}-{package.version}{PLUGIN_PACKAGE_EXTENSION}"
    destination = market_dir / filename
    source_path = Path(path).expanduser()
    if source_path.is_dir():
        _zip_directory(source_path, destination)
    else:
        shutil.copyfile(source_path, destination)
    market_package = package_from_path(destination, source="market", package_path=str(destination))
    return market_package, destination


def discover_market_packages(market_dir: Path) -> list[PluginPackage]:
    if not market_dir.exists():
        return []
    packages = [
        package_from_path(path, source="market", package_path=str(path))
        for path in sorted(market_dir.glob(f"*{PLUGIN_PACKAGE_EXTENSION}"))
    ]
    for manifest_path in sorted(market_dir.glob("*/plugin.yaml")):
        packages.append(package_from_path(manifest_path.parent, source="market", package_path=str(manifest_path.parent)))
    return packages


def install_market_package(package_path: Path, installed_plugins_dir: Path) -> tuple[PluginPackage, Path]:
    market_package = package_from_path(package_path, source="market", package_path=str(package_path))
    destination = installed_plugins_dir / safe_package_dir_name(market_package.package_id) / market_package.version
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    if package_path.is_dir():
        shutil.copytree(package_path, destination, dirs_exist_ok=True)
    else:
        with zipfile.ZipFile(package_path) as archive:
            _safe_extract(archive, destination)
    package = package_from_path(destination, source="installed", package_path=str(destination))
    return package, destination


def discover_installed_packages(installed_plugins_dir: Path) -> list[PluginPackage]:
    if not installed_plugins_dir.exists():
        return []
    return [
        package_from_path(manifest_path.parent, source="installed", package_path=str(manifest_path.parent))
        for manifest_path in sorted(installed_plugins_dir.glob("*/*/plugin.yaml"))
    ]


def load_installed_plugin_class(installed_path: str | Path, entrypoint: str) -> type[PluginBase]:
    module_file, _, class_name = entrypoint.partition(":")
    if not module_file or not class_name:
        raise ValueError("runtime.entrypoint must use '<file.py>:<ClassName>'")
    plugin_file = Path(installed_path) / module_file
    if not plugin_file.exists():
        raise ValueError(f"plugin entrypoint file does not exist: {plugin_file}")
    module_name = f"plugin_agent_external_{abs(hash((str(plugin_file), class_name)))}"
    spec = importlib.util.spec_from_file_location(module_name, plugin_file)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load plugin module: {plugin_file}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    installed_root = str(Path(installed_path).resolve())
    before_modules = set(sys.modules)
    sys.path.insert(0, installed_root)
    try:
        spec.loader.exec_module(module)
    finally:
        try:
            sys.path.remove(installed_root)
        except ValueError:
            pass
        for name in set(sys.modules) - before_modules - {module_name}:
            loaded = sys.modules.get(name)
            loaded_file = getattr(loaded, "__file__", None)
            if loaded_file and Path(loaded_file).resolve().is_relative_to(Path(installed_root)):
                sys.modules.pop(name, None)
    plugin_class = getattr(module, class_name, None)
    if plugin_class is None:
        raise ValueError(f"plugin class {class_name} is not defined")
    if not issubclass(plugin_class, PluginBase):
        raise ValueError(f"plugin class {class_name} must extend plugin_agent_sdk.Plugin")
    return plugin_class


def _descriptor_from_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    if "descriptor" in manifest:
        descriptor = manifest.get("descriptor") or {}
    else:
        descriptor = {
            "id": manifest.get("id"),
            "version": manifest.get("version", "1.0.0"),
            "name": manifest.get("name"),
            "author": manifest.get("author"),
            "description": manifest.get("description"),
            "categories": manifest.get("categories", []),
            "tags": manifest.get("tags", []),
            "provides": manifest.get("provides", []),
            "requires": manifest.get("requires", []),
            "config_schema_ref": manifest.get("config_schema_ref"),
        }
    if not descriptor.get("id"):
        raise ValueError("plugin id is required")
    if not descriptor.get("name"):
        raise ValueError("plugin name is required")
    if not descriptor.get("description"):
        raise ValueError("plugin description is required")
    return descriptor


def _read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML object")
    return data


def _zip_directory(source_dir: Path, destination: Path) -> None:
    with zipfile.ZipFile(destination, "w") as archive:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source_dir).as_posix())


def _safe_extract(archive: zipfile.ZipFile, destination: Path) -> None:
    destination = destination.resolve()
    for member in archive.infolist():
        target = (destination / member.filename).resolve()
        if not str(target).startswith(str(destination)):
            raise ValueError("plugin package contains an unsafe path")
    archive.extractall(destination)
