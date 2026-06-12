from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Iterator

from packaging.specifiers import InvalidSpecifier, SpecifierSet

from plugin_agent.kernel import KernelInvokeError
from plugin_agent.runtime.protocol import HostMethod, PluginMethod, WorkerMethod
from plugin_agent_sdk import PluginPackage, RuntimeSpec, SchemaDefinition

logger = logging.getLogger(__name__)
WORKER_CLEANUP_INTERVAL_SECONDS = 30.0


class WorkerRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class _PendingRequest:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.result: Any = None
        self.error: dict[str, Any] | None = None


class _WorkerConnection:
    def __init__(
        self,
        key: str,
        package: PluginPackage,
        runtime_dir: Path,
        env_python: Path | None,
        host_python_path: str,
    ) -> None:
        self.key = key
        self.package = package
        self.runtime_dir = runtime_dir
        self.env_python = env_python
        self.host_python_path = host_python_path
        self.process: subprocess.Popen[str] | None = None
        self.lock = threading.Lock()
        self.process_lock = threading.Lock()
        self.pending: dict[str, _PendingRequest] = {}
        self.streams: dict[str, queue.Queue[tuple[str, Any]]] = {}
        self.kernels_by_instance: dict[str, Any] = {}
        self.last_used = time.monotonic()
        self._next_id = 0
        self._reader_thread: threading.Thread | None = None

    @property
    def status(self) -> str:
        if not self.process:
            return "stopped"
        return "running" if self.process.poll() is None else "stopped"

    @property
    def is_busy(self) -> bool:
        with self.lock:
            return bool(self.pending or self.streams)

    def start(self) -> None:
        with self.process_lock:
            if self.process and self.process.poll() is None:
                return
            python = str(self.env_python or Path(sys.executable))
            env = os.environ.copy()
            env["PYTHONPATH"] = self.host_python_path
            self.process = subprocess.Popen(
                [python, "-m", "plugin_agent.worker_main"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=None,
                text=True,
                bufsize=1,
                env=env,
            )
            self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
            self._reader_thread.start()
            logger.info("Plugin worker started key=%s pid=%s", self.key, self.process.pid)

    def shutdown(self) -> None:
        if not self.process:
            return
        try:
            if self.process.poll() is None:
                self.request(WorkerMethod.SHUTDOWN, {}, timeout=2)
        except Exception:
            pass
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        logger.info("Plugin worker stopped key=%s", self.key)

    def request(self, method: str, params: dict[str, Any], timeout: float | None) -> Any:
        request_id = self._send_request(method, params)
        with self.lock:
            pending = self.pending[request_id]
        try:
            if not pending.event.wait(timeout):
                raise TimeoutError(f"worker request timed out: {method}")
            if pending.error:
                raise WorkerRuntimeError(
                    str(pending.error.get("code") or "worker_error"),
                    str(pending.error.get("message") or "worker request failed"),
                    pending.error.get("details") or {},
                )
            return pending.result
        finally:
            with self.lock:
                self.pending.pop(request_id, None)

    def stream_request(self, method: str, params: dict[str, Any], timeout: float | None) -> Iterator[dict[str, Any]]:
        request_id = self._next_request_id()
        stream_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        with self.lock:
            self.streams[request_id] = stream_queue
        self._send_request_with_id(request_id, method, params)
        try:
            while True:
                try:
                    kind, value = stream_queue.get(timeout=timeout)
                except queue.Empty as exc:
                    raise TimeoutError(f"worker stream timed out: {method}") from exc
                if kind == "event":
                    yield value
                    continue
                if kind == "error":
                    raise WorkerRuntimeError(
                        str(value.get("code") or "worker_error"),
                        str(value.get("message") or "worker stream failed"),
                        value.get("details") or {},
                    )
                return
        finally:
            with self.lock:
                self.streams.pop(request_id, None)
                self.pending.pop(request_id, None)

    def _send_request(self, method: str, params: dict[str, Any]) -> str:
        request_id = self._next_request_id()
        self._send_request_with_id(request_id, method, params)
        return request_id

    def _next_request_id(self) -> str:
        with self.lock:
            self._next_id += 1
            request_id = f"{self.key}-{self._next_id}"
            self.pending[request_id] = _PendingRequest()
            return request_id

    def _send_request_with_id(self, request_id: str, method: str, params: dict[str, Any]) -> None:
        if not self.process or self.process.poll() is not None or not self.process.stdin:
            self.start()
        assert self.process and self.process.stdin
        with self.lock:
            self.process.stdin.write(
                json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}) + "\n"
            )
            self.process.stdin.flush()
            self.last_used = time.monotonic()

    def _send_response(self, request_id: str, result: Any = None, error: dict[str, Any] | None = None) -> None:
        if not self.process or not self.process.stdin:
            return
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
        if error is not None:
            message["error"] = error
        else:
            message["result"] = result
        with self.lock:
            self.process.stdin.write(json.dumps(message) + "\n")
            self.process.stdin.flush()

    def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        if not self.process or not self.process.stdin:
            return
        with self.lock:
            self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n")
            self.process.stdin.flush()

    def _read_loop(self) -> None:
        assert self.process and self.process.stdout
        for line in self.process.stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Ignoring malformed plugin worker protocol line key=%s", self.key)
                continue
            if "id" in message and "method" not in message:
                self._handle_response(message)
                continue
            method = message.get("method")
            if method == PluginMethod.STREAM_EVENT:
                params = message.get("params") or {}
                stream_queue = self.streams.get(str(params.get("request_id")))
                if stream_queue:
                    stream_queue.put(("event", params.get("event")))
                continue
            if isinstance(method, str) and method.startswith(HostMethod.PREFIX):
                threading.Thread(target=self._handle_host_request, args=(message,), daemon=True).start()
                continue
            logger.warning("Ignoring unknown plugin worker message key=%s method=%s", self.key, method)

    def _handle_response(self, message: dict[str, Any]) -> None:
        request_id = str(message.get("id"))
        with self.lock:
            pending = self.pending.get(request_id)
            stream_queue = self.streams.get(request_id)
        if "error" in message:
            if stream_queue:
                stream_queue.put(("error", message["error"]))
            if pending:
                pending.error = message["error"]
                pending.event.set()
            return
        if stream_queue:
            stream_queue.put(("done", message.get("result")))
        if pending:
            pending.result = message.get("result")
            pending.event.set()

    def _handle_host_request(self, message: dict[str, Any]) -> None:
        request_id = str(message.get("id"))
        method = message.get("method")
        params = message.get("params") or {}
        caller_instance_id = str(params.get("caller_instance_id") or "")
        kernel = self.kernels_by_instance.get(caller_instance_id)
        if kernel is None:
            self._send_response(
                request_id,
                error={"code": "host_kernel_unavailable", "message": f"no host kernel for {caller_instance_id}"},
            )
            return
        try:
            context = dict(params.get("context") or {})
            context.setdefault("caller_instance_id", caller_instance_id)
            if method == HostMethod.INVOKE:
                result = kernel.invoke(params["capability"], params.get("payload") or {}, context).model_dump()
                self._send_response(request_id, result=result)
                return
            if method == HostMethod.COLLECT_TOOL_DEFINITIONS:
                result = [tool.model_dump() for tool in kernel.collect_tool_definitions()]
                self._send_response(request_id, result=result)
                return
            if method == HostMethod.CAPABILITY_HAS:
                self._send_response(request_id, result={"has": kernel.capability_registry.has(params["capability"])})
                return
            if method == HostMethod.SCHEMA_GET:
                self._send_response(request_id, result={"json_schema": kernel.get_schema(params["schema_ref"])})
                return
            if method == HostMethod.SCHEMA_VALIDATE:
                kernel.schema_registry.validate_payload(params.get("schema_ref"), params.get("payload") or {}, params.get("phase") or "payload")
                self._send_response(request_id, result={"ok": True})
                return
            if method == HostMethod.SCHEMA_REGISTER:
                kernel.schema_registry.register(SchemaDefinition.model_validate(params["schema"]))
                self._send_response(request_id, result={"ok": True})
                return
            for event in kernel.stream(params["capability"], params.get("payload") or {}, context):
                self._send_notification(HostMethod.STREAM_EVENT, {"request_id": request_id, "event": event})
            self._send_response(request_id, result={"ok": True})
        except KernelInvokeError as exc:
            self._send_response(request_id, error=exc.error)
        except Exception as exc:
            self._send_response(request_id, error={"code": "host_callback_error", "message": str(exc)})


class PluginRuntimeManager:
    def __init__(self, runtime_dir: Path) -> None:
        self.runtime_dir = Path(runtime_dir)
        self.env_root = self.runtime_dir / "plugin-envs"
        self.state_root = self.runtime_dir / "plugin-state"
        self.cache_root = self.runtime_dir / "plugin-cache"
        self.temp_root = self.runtime_dir / "tmp"
        self.workers: dict[str, _WorkerConnection] = {}
        self.env_status: dict[str, str] = {}
        self.lock = threading.Lock()
        self._env_locks: dict[str, threading.Lock] = {}
        self._cleanup_stop = threading.Event()
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()

    def runtime_context(
        self,
        package: PluginPackage,
        agent_id: str,
        instance_id: str,
        installed_path: str,
    ) -> dict[str, str]:
        state_root = self.state_root / agent_id / instance_id
        if package.runtime.isolation.state == "shared":
            state_root = self.state_root / "shared" / package.package_id / package.version
        cache_root = self.cache_root / package.package_id / package.version
        temp_root = self.temp_root / agent_id / instance_id
        for path in (state_root, cache_root, temp_root):
            path.mkdir(parents=True, exist_ok=True)
        return {
            "agent_id": agent_id,
            "instance_id": instance_id,
            "package_id": package.package_id,
            "package_version": package.version,
            "plugin_dir": str(Path(installed_path).resolve()),
            "state_dir": str(state_root.resolve()),
            "cache_dir": str(cache_root.resolve()),
            "temp_dir": str(temp_root.resolve()),
        }

    def start_instance(
        self,
        package: PluginPackage,
        installed_path: str,
        entrypoint: str,
        config: dict[str, Any],
        instance_id: str,
        agent_id: str,
        host_kernel: Any,
    ) -> dict[str, Any]:
        worker = self._get_worker(package, instance_id)
        worker.kernels_by_instance[instance_id] = host_kernel
        runtime_context = self.runtime_context(package, agent_id, instance_id, installed_path)
        timeout = package.runtime.worker.start_timeout_seconds
        worker.request(
            PluginMethod.CREATE_INSTANCE,
            {
                "package": package.model_dump(),
                "installed_path": installed_path,
                "entrypoint": entrypoint,
                "config": config,
                "instance_id": instance_id,
                "runtime_context": runtime_context,
            },
            timeout=timeout,
        )
        worker.request(PluginMethod.START, {"instance_id": instance_id}, timeout=timeout)
        description = worker.request(PluginMethod.DESCRIBE, {"instance_id": instance_id}, timeout=timeout)
        runtime_context["tool_definitions"] = description.get("tool_definitions", [])
        runtime_context["resources"] = description.get("resources", [])
        return runtime_context

    def after_start_all(self, package: PluginPackage, instance_id: str, host_kernel: Any) -> dict[str, Any]:
        worker = self._get_worker(package, instance_id)
        worker.kernels_by_instance[instance_id] = host_kernel
        worker.request(PluginMethod.AFTER_START_ALL, {"instance_id": instance_id}, timeout=package.runtime.worker.start_timeout_seconds)
        return worker.request(PluginMethod.DESCRIBE, {"instance_id": instance_id}, timeout=package.runtime.worker.start_timeout_seconds)

    def invoke(
        self,
        package: PluginPackage,
        instance_id: str,
        capability: str,
        payload: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        worker = self._get_worker(package, instance_id)
        return worker.request(
            PluginMethod.INVOKE,
            {"instance_id": instance_id, "capability": capability, "payload": payload, "context": context},
            timeout=package.runtime.worker.invoke_timeout_seconds,
        )

    def stream(
        self,
        package: PluginPackage,
        instance_id: str,
        capability: str,
        payload: dict[str, Any],
        context: dict[str, Any],
    ) -> Iterator[dict[str, Any]]:
        worker = self._get_worker(package, instance_id)
        yield from worker.stream_request(
            PluginMethod.STREAM,
            {"instance_id": instance_id, "capability": capability, "payload": payload, "context": context},
            timeout=package.runtime.worker.invoke_timeout_seconds,
        )

    def stop_instance(self, package: PluginPackage, instance_id: str) -> None:
        with self.lock:
            worker = self.workers.get(self._worker_key(package, instance_id))
        if worker is None:
            return
        try:
            worker.request(PluginMethod.STOP_INSTANCE, {"instance_id": instance_id}, timeout=5)
        finally:
            worker.kernels_by_instance.pop(instance_id, None)

    def worker_status(self, package: PluginPackage, instance_id: str | None = None) -> str:
        key = self._worker_key(package, instance_id or "")
        with self.lock:
            worker = self.workers.get(key)
        return worker.status if worker else "stopped"

    def cleanup_idle_workers(self) -> None:
        now = time.monotonic()
        stale_workers: list[tuple[str, _WorkerConnection]] = []
        with self.lock:
            workers = list(self.workers.items())
        for key, worker in workers:
            timeout = worker.package.runtime.worker.idle_timeout_seconds
            if worker.status == "running" and not worker.is_busy and now - worker.last_used > timeout:
                stale_workers.append((key, worker))
        for key, worker in stale_workers:
            worker.shutdown()
            with self.lock:
                if self.workers.get(key) is worker:
                    self.workers.pop(key, None)

    def shutdown(self) -> None:
        self._cleanup_stop.set()
        with self.lock:
            workers = list(self.workers.items())
            self.workers.clear()
        for _, worker in workers:
            worker.shutdown()

    def _get_worker(self, package: PluginPackage, instance_id: str) -> _WorkerConnection:
        key = self._worker_key(package, instance_id)
        with self.lock:
            worker = self.workers.get(key)
        if worker is not None:
            worker.start()
            return worker
        env_lock = self._env_lock(f"{package.package_id}@{package.version}")
        with env_lock:
            env_python = self._ensure_environment(package)
        new_worker = _WorkerConnection(
            key,
            package,
            self.runtime_dir,
            env_python,
            host_python_path=self._host_python_path(),
        )
        with self.lock:
            worker = self.workers.get(key)
            if worker is None:
                self.workers[key] = new_worker
                worker = new_worker
            else:
                new_worker = worker
        worker.start()
        return worker

    def _env_lock(self, key: str) -> threading.Lock:
        with self.lock:
            lock = self._env_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._env_locks[key] = lock
            return lock

    def _cleanup_loop(self) -> None:
        while not self._cleanup_stop.wait(WORKER_CLEANUP_INTERVAL_SECONDS):
            try:
                self.cleanup_idle_workers()
            except Exception:
                logger.exception("Plugin worker cleanup failed")

    def _worker_key(self, package: PluginPackage, instance_id: str) -> str:
        if package.runtime.isolation.process == "instance":
            return f"{package.package_id}@{package.version}:{instance_id}"
        return f"{package.package_id}@{package.version}"

    def _ensure_environment(self, package: PluginPackage) -> Path | None:
        self._check_python_requirement(package.runtime)
        env_key = f"{package.package_id}@{package.version}"
        dependencies = package.runtime.python.dependencies
        if not dependencies:
            self.env_status[env_key] = "using_host"
            return None
        uv = shutil.which("uv")
        if not uv:
            self.env_status[env_key] = "failed"
            raise WorkerRuntimeError("worker_env_failed", "uv is required to install plugin worker dependencies")
        venv_dir = self.env_root / package.package_id / package.version / ".venv"
        python = venv_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        deps_hash = hashlib.sha256(json.dumps(dependencies, sort_keys=True).encode("utf-8")).hexdigest()
        stamp_path = venv_dir.parent / "dependencies.sha256"
        if python.exists() and stamp_path.exists() and stamp_path.read_text().strip() == deps_hash:
            self.env_status[env_key] = "ready"
            return python
        try:
            if not python.exists():
                venv_dir.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run([uv, "venv", str(venv_dir), "--python", sys.executable], check=True, capture_output=True, text=True)
            subprocess.run([uv, "pip", "install", "--python", str(python), *dependencies], check=True, capture_output=True, text=True)
            stamp_path.write_text(deps_hash)
        except subprocess.CalledProcessError as exc:
            self.env_status[env_key] = "failed"
            details = {"returncode": exc.returncode, "stdout": exc.stdout, "stderr": exc.stderr}
            message = (exc.stderr or exc.stdout or str(exc)).strip()
            raise WorkerRuntimeError("worker_env_failed", message, details) from exc
        self.env_status[env_key] = "ready"
        return python

    def _check_python_requirement(self, runtime: RuntimeSpec) -> None:
        requirement = runtime.python.requires_python
        if not requirement:
            return
        try:
            specifier = SpecifierSet(requirement)
        except InvalidSpecifier as exc:
            raise WorkerRuntimeError("worker_env_failed", f"invalid requires_python: {requirement}") from exc
        current = ".".join(str(part) for part in sys.version_info[:3])
        if current not in specifier:
            raise WorkerRuntimeError(
                "worker_env_failed",
                f"current Python {current} does not satisfy plugin requirement {requirement}",
            )

    def _host_python_path(self) -> str:
        backend_src = str(Path(__file__).resolve().parents[2])
        existing = os.environ.get("PYTHONPATH")
        return backend_src if not existing else os.pathsep.join([backend_src, existing])
