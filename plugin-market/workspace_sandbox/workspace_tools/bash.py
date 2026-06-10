from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from workspace_tools.context import WorkspaceContext


def run_bash(workspace: WorkspaceContext, payload: dict[str, Any]) -> dict[str, Any]:
    command = str(payload["command"])
    workspace.check_command_policy(command)
    cwd = workspace.resolve_existing(str(payload.get("cwd") or "."))
    if not cwd.is_dir():
        raise ValueError("cwd must be a directory")
    sandbox_config = workspace.config.get("sandbox", {})
    timeout_ms = int(payload.get("timeout_ms", sandbox_config.get("command_timeout_ms", 30000)))
    max_output_bytes = int(sandbox_config.get("max_output_bytes", 200000))
    sandbox_enabled = bool(sandbox_config.get("enabled", True))
    started = time.monotonic()
    argv = ["/bin/bash", "-lc", command]
    backend = "none"
    env = {**os.environ, "PLUGIN_AGENT_SANDBOX": "workspace"}
    if sandbox_enabled:
        if platform.system() != "Darwin":
            raise RuntimeError("workspace.bash sandbox backend is only implemented on macOS in v1")
        sandbox_exec = shutil.which("sandbox-exec") or "/usr/bin/sandbox-exec"
        if not Path(sandbox_exec).exists():
            raise RuntimeError("sandbox-exec is not available")
        backend = "seatbelt"
        argv = [sandbox_exec, "-p", workspace.seatbelt_profile(bool(sandbox_config.get("network_access", False))), *argv]
    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd),
            env=env,
            text=True,
            capture_output=True,
            timeout=max(timeout_ms, 1) / 1000,
        )
        stdout, stdout_truncated = workspace.truncate(completed.stdout, max_output_bytes)
        stderr, stderr_truncated = workspace.truncate(completed.stderr, max_output_bytes)
        return {
            "ok": completed.returncode == 0,
            "exit_code": completed.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
            "timed_out": False,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "sandbox_backend": backend,
        }
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode("utf-8", errors="replace")
        stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode("utf-8", errors="replace")
        stdout, stdout_truncated = workspace.truncate(stdout, max_output_bytes)
        stderr, stderr_truncated = workspace.truncate(stderr, max_output_bytes)
        return {
            "ok": False,
            "exit_code": None,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
            "timed_out": True,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "sandbox_backend": backend,
        }
