from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

from plugin_agent.kernel import AgentKernel
from plugin_agent.runtime import RemotePluginProxy
from plugin_agent.services.assembly_service import AgentAssemblyService
from plugin_agent_sdk import Plugin


class HostEchoPlugin(Plugin):
    descriptor = {
        "id": "host.echo",
        "version": "1.0.0",
        "provides": [{"name": "host.echo", "version": "1.0.0"}],
    }

    def invoke(self, capability, payload, context):
        if capability == "host.echo":
            return {"text": payload["text"], "caller": context.get("caller_instance_id")}
        return super().invoke(capability, payload, context)

    def stream(self, capability, payload, context):
        if capability == "host.echo.stream":
            yield {"type": "host_delta", "payload": {"text": payload["text"]}}
            return
        yield from super().stream(capability, payload, context)


class HostStreamingEchoPlugin(HostEchoPlugin):
    descriptor = {
        "id": "host.echo_streaming",
        "version": "1.0.0",
        "provides": [
            {"name": "host.echo", "version": "1.0.0"},
            {"name": "host.echo.stream", "version": "1.0.0"},
        ],
    }


def write_worker_plugin(
    root: Path,
    package_id: str = "worker.echo",
    version: str = "1.0.0",
    process_scope: str = "package_version",
    state_scope: str = "instance",
    idle_timeout_seconds: int = 60,
) -> Path:
    package_dir = root / f"{package_id.replace('.', '_')}_{version.replace('.', '_')}"
    package_dir.mkdir(parents=True)
    package_dir.joinpath("plugin.yaml").write_text(
        textwrap.dedent(
            f"""
            id: {package_id}
            version: {version}
            name: Worker Echo
            description: Worker runtime echo test plugin.
            runtime:
              type: python.worker
              entrypoint: plugin.py:WorkerEchoPlugin
              isolation:
                process: {process_scope}
                state: {state_scope}
              worker:
                idle_timeout_seconds: {idle_timeout_seconds}
                start_timeout_seconds: 10
                invoke_timeout_seconds: 10
            provides:
              - name: worker.echo
                version: 1.0.0
              - name: worker.echo.stream
                version: 1.0.0
              - name: worker.host_echo
                version: 1.0.0
              - name: worker.host_echo.stream
                version: 1.0.0
            """
        ).strip()
    )
    package_dir.joinpath("plugin.py").write_text(
        textwrap.dedent(
            """
            from plugin_agent_sdk import Plugin

            class WorkerEchoPlugin(Plugin):
                def start(self, kernel):
                    super().start(kernel)
                    self.counter = 0

                def invoke(self, capability, payload, context):
                    if capability == "worker.echo":
                        self.counter += 1
                        return {
                            "text": payload.get("text", ""),
                            "counter": self.counter,
                            "instance_id": self.instance_id,
                            "state_dir": self.runtime_context.state_dir,
                        }
                    if capability == "worker.host_echo":
                        response = self.kernel.invoke(
                            "host.echo",
                            {"text": payload.get("text", "")},
                            context,
                        ).payload
                        return {"host": response, "instance_id": self.instance_id}
                    return super().invoke(capability, payload, context)

                def stream(self, capability, payload, context):
                    if capability == "worker.echo.stream":
                        yield {"type": "worker_delta", "payload": {"text": payload.get("text", "")}}
                        yield {"type": "worker_done", "payload": {"instance_id": self.instance_id}}
                        return
                    if capability == "worker.host_echo.stream":
                        for event in self.kernel.stream("host.echo.stream", {"text": payload.get("text", "")}, context):
                            yield {"type": "worker_forwarded", "payload": event}
                        yield {"type": "worker_done", "payload": {"instance_id": self.instance_id}}
                        return
                    yield from super().stream(capability, payload, context)
            """
        ).strip()
    )
    return package_dir


def install_worker_package(service: AgentAssemblyService, package_dir: Path) -> dict:
    service.reserve_upload({"path": str(package_dir)})
    package_id = package_dir.joinpath("plugin.yaml").read_text().split("id: ", 1)[1].splitlines()[0].strip()
    return service.install_market_plugin({"package_id": package_id})


def test_worker_runtime_uses_package_version_worker_with_isolated_instances(tmp_path):
    service = AgentAssemblyService(runtime_dir=tmp_path / "runtime", market_dir=tmp_path / "market")
    installed = install_worker_package(service, write_worker_plugin(tmp_path / "packages"))
    assert installed["plugin_package"]["runtime"]["type"] == "python.worker"

    agent_a = service.create_agent("Agent A", plugin_instances=[{"package_id": "worker.echo"}])
    agent_b = service.create_agent("Agent B", plugin_instances=[{"package_id": "worker.echo"}])
    instance_a = agent_a["plugin_instances"][0]["instance_id"]
    instance_b = agent_b["plugin_instances"][0]["instance_id"]
    kernel_a = service.build_kernel_for_agent(agent_a["id"])
    kernel_b = service.build_kernel_for_agent(agent_b["id"])
    try:
        plugin_a = kernel_a.plugins[instance_a]
        plugin_b = kernel_b.plugins[instance_b]

        assert isinstance(plugin_a, RemotePluginProxy)
        assert isinstance(plugin_b, RemotePluginProxy)
        assert plugin_a.manager is plugin_b.manager
        assert len(service.runtime_manager.workers) == 1

        first = kernel_a.invoke("worker.echo", {"text": "a"}).payload
        second = kernel_b.invoke("worker.echo", {"text": "b"}).payload

        assert first["counter"] == 1
        assert second["counter"] == 1
        assert first["instance_id"] != second["instance_id"]
        assert first["state_dir"] != second["state_dir"]
    finally:
        kernel_a.stop_all()
        kernel_b.stop_all()


def test_worker_runtime_can_isolate_process_per_instance(tmp_path):
    service = AgentAssemblyService(runtime_dir=tmp_path / "runtime", market_dir=tmp_path / "market")
    install_worker_package(
        service,
        write_worker_plugin(tmp_path / "packages", package_id="worker.echo_instance", process_scope="instance"),
    )

    agent_a = service.create_agent("Agent A", plugin_instances=[{"package_id": "worker.echo_instance"}])
    agent_b = service.create_agent("Agent B", plugin_instances=[{"package_id": "worker.echo_instance"}])
    kernel_a = service.build_kernel_for_agent(agent_a["id"])
    kernel_b = service.build_kernel_for_agent(agent_b["id"])
    try:
        assert len(service.runtime_manager.workers) == 2
    finally:
        kernel_a.stop_all()
        kernel_b.stop_all()


def test_worker_runtime_invokes_host_capability_over_json_rpc(tmp_path):
    service = AgentAssemblyService(runtime_dir=tmp_path / "runtime", market_dir=tmp_path / "market")
    install_worker_package(service, write_worker_plugin(tmp_path / "packages"))
    worker_instance = "worker-1"
    kernel = AgentKernel()
    kernel.load_plugins(
        [
            HostEchoPlugin(instance_id="host-echo"),
            service.instantiate_plugin("worker.echo", instance_id=worker_instance, agent_id="agent-test"),
        ]
    )
    kernel.start_all()
    try:
        result = kernel.invoke("worker.host_echo", {"text": "hello"}, {"agent_id": "agent-test"}).payload

        assert result == {"host": {"text": "hello", "caller": worker_instance}, "instance_id": worker_instance}
    finally:
        kernel.stop_all()


def test_worker_runtime_streams_host_capability_over_json_rpc(tmp_path):
    service = AgentAssemblyService(runtime_dir=tmp_path / "runtime", market_dir=tmp_path / "market")
    install_worker_package(service, write_worker_plugin(tmp_path / "packages"))
    kernel = AgentKernel()
    kernel.load_plugins(
        [
            HostStreamingEchoPlugin(instance_id="host-stream"),
            service.instantiate_plugin("worker.echo", instance_id="worker-1", agent_id="agent-test"),
        ]
    )
    kernel.start_all()
    try:
        events = list(kernel.stream("worker.host_echo.stream", {"text": "hello"}, {"agent_id": "agent-test"}))

        assert events[0] == {"type": "worker_forwarded", "payload": {"type": "host_delta", "payload": {"text": "hello"}}}
        assert events[-1]["type"] == "worker_done"
    finally:
        kernel.stop_all()


def test_worker_runtime_rejects_missing_uv_for_dependencies(tmp_path, monkeypatch):
    service = AgentAssemblyService(runtime_dir=tmp_path / "runtime", market_dir=tmp_path / "market")
    package_dir = write_worker_plugin(tmp_path / "packages", package_id="worker.with_dep")
    package_dir.joinpath("plugin.yaml").write_text(
        package_dir.joinpath("plugin.yaml").read_text().replace(
            "runtime:\n  type: python.worker",
            "runtime:\n  type: python.worker\n  python:\n    dependencies:\n      - definitely-not-installed-package==0.0.1",
        )
    )
    install_worker_package(service, package_dir)
    agent = service.create_agent("Agent", plugin_instances=[{"package_id": "worker.with_dep"}])
    monkeypatch.setattr("plugin_agent.runtime.manager.shutil.which", lambda _: None)

    runtime = service.agent_runtime(agent["id"])

    assert runtime["status"] == "failed"
    assert any(diagnostic["code"] == "worker_env_failed" for diagnostic in runtime["diagnostics"])


def test_worker_runtime_cleanup_stops_idle_workers(tmp_path):
    service = AgentAssemblyService(runtime_dir=tmp_path / "runtime", market_dir=tmp_path / "market")
    install_worker_package(service, write_worker_plugin(tmp_path / "packages", idle_timeout_seconds=0))
    agent = service.create_agent("Agent", plugin_instances=[{"package_id": "worker.echo"}])
    kernel = service.build_kernel_for_agent(agent["id"])
    assert len(service.runtime_manager.workers) == 1

    kernel.stop_all()
    service.runtime_manager.cleanup_idle_workers()

    assert service.runtime_manager.workers == {}


def test_worker_runtime_reports_dependency_install_failure(tmp_path, monkeypatch):
    service = AgentAssemblyService(runtime_dir=tmp_path / "runtime", market_dir=tmp_path / "market")
    package_dir = write_worker_plugin(tmp_path / "packages", package_id="worker.bad_dep")
    package_dir.joinpath("plugin.yaml").write_text(
        package_dir.joinpath("plugin.yaml").read_text().replace(
            "runtime:\n  type: python.worker",
            "runtime:\n  type: python.worker\n  python:\n    dependencies:\n      - bad-package==0.0.1",
        )
    )
    install_worker_package(service, package_dir)
    agent = service.create_agent("Agent", plugin_instances=[{"package_id": "worker.bad_dep"}])
    monkeypatch.setattr("plugin_agent.runtime.manager.shutil.which", lambda _: "/usr/bin/uv")

    def fail_run(*args, **kwargs):
        raise subprocess.CalledProcessError(2, args[0], stderr="dependency install failed")

    monkeypatch.setattr("plugin_agent.runtime.manager.subprocess.run", fail_run)

    runtime = service.agent_runtime(agent["id"])

    assert runtime["status"] == "failed"
    assert any(
        diagnostic["code"] == "worker_env_failed" and "dependency install failed" in diagnostic["message"]
        for diagnostic in runtime["diagnostics"]
    )
