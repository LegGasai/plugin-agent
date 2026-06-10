from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any


NOISY_DIRS = {".git", "node_modules", ".cache", "dist", "coverage", "__pycache__"}


class WorkspaceContext:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.root: Path | None = None
        self.reads: dict[str, tuple[float, int]] = {}

    def start(self) -> None:
        configured = str(self.config.get("workspace_root") or "").strip()
        if not configured:
            raise ValueError("workspace_root is required")
        root = Path(configured).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise ValueError(f"workspace_root must be an existing directory: {root}")
        self.root = root

    def root_path(self) -> Path:
        if self.root is None:
            raise RuntimeError("workspace sandbox plugin is not started")
        return self.root

    def resolve_existing(self, requested: str) -> Path:
        root = self.root_path()
        target = Path(requested).expanduser()
        if not target.is_absolute():
            target = root / target
        resolved = target.resolve(strict=True)
        if not resolved.is_relative_to(root):
            raise ValueError("path is outside workspace")
        return resolved

    def resolve_for_create(self, requested: str) -> Path:
        root = self.root_path()
        target = Path(requested).expanduser()
        if not target.is_absolute():
            target = root / target
        resolved = target.resolve(strict=False)
        if not resolved.is_relative_to(root):
            raise ValueError("path is outside workspace")
        parent = resolved.parent
        if parent.exists() and not parent.resolve(strict=True).is_relative_to(root):
            raise ValueError("path is outside workspace")
        return resolved

    def relative(self, path: Path) -> str:
        relative = path.resolve(strict=False).relative_to(self.root_path())
        return relative.as_posix()

    def is_hidden_or_noisy(self, relative_path: str) -> bool:
        return any(part.startswith(".") or part in NOISY_DIRS for part in relative_path.split("/"))

    def walk_files(self, start: Path) -> list[Path]:
        files: list[Path] = []
        for path in start.rglob("*"):
            relative = self.relative(path)
            if self.is_hidden_or_noisy(relative):
                continue
            if path.is_file():
                files.append(path)
        return sorted(files, key=self.relative)

    def max_file_bytes(self) -> int:
        return int(self.config.get("filesystem", {}).get("max_file_bytes", 1048576))

    def protected_patterns(self) -> list[str]:
        return list(self.config.get("filesystem", {}).get("protected_paths", [".git", ".plugin-agent", ".env", ".env.*"]))

    def ensure_writable(self, path: Path) -> None:
        relative = self.relative(path)
        for pattern in self.protected_patterns():
            normalized = pattern.rstrip("/")
            if relative == normalized or relative.startswith(f"{normalized}/") or fnmatch.fnmatch(relative, pattern):
                raise ValueError(f"cannot write protected path: {relative}")

    def check_command_policy(self, command: str) -> None:
        sandbox_config = self.config.get("sandbox", {})
        for pattern in sandbox_config.get("denied_patterns", []):
            if fnmatch.fnmatch(command, pattern):
                raise ValueError(f"command denied by policy: {pattern}")
        allowed = sandbox_config.get("allowed_commands", [])
        if allowed and not any(fnmatch.fnmatch(command, pattern) for pattern in allowed):
            raise ValueError("command is not allowed by policy")

    def truncate(self, text: str, max_bytes: int) -> tuple[str, bool]:
        raw = text.encode("utf-8")
        if len(raw) <= max_bytes:
            return text, False
        return raw[:max_bytes].decode("utf-8", errors="replace"), True

    def seatbelt_profile(self, network_access: bool) -> str:
        root = self.root_path()
        write_filters = [f'(subpath "{self._sbpl(root)}")']
        protected_filters = []
        for pattern in self.protected_patterns():
            if any(char in pattern for char in "*?[]"):
                continue
            protected = (root / pattern).resolve(strict=False)
            protected_filters.append(f'(subpath "{self._sbpl(protected)}")')
        if protected_filters:
            denied_filters = " ".join(f"(require-not {item})" for item in protected_filters)
            write_filters = [f"(require-all {write_filters[0]} {denied_filters})"]
        tmp_filters = [f'(subpath "{self._sbpl(Path("/tmp"))}")', f'(subpath "{self._sbpl(Path("/private/tmp"))}")']
        network = "\n(allow network*)\n" if network_access else ""
        return f"""
(version 1)
(deny default)
(allow process*)
(allow signal (target same-sandbox))
(allow sysctl-read)
(allow file-read*)
(allow file-write* {' '.join(write_filters + tmp_filters)})
{network}
""".strip()

    def _sbpl(self, path: Path) -> str:
        return str(path).replace("\\", "\\\\").replace('"', '\\"')
