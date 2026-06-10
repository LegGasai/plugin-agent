from __future__ import annotations

import json
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from plugin_agent.assembly import AgentAssemblyService
from plugin_agent.http_service import PluginAgentHTTPServer, create_app_state
from plugin_agent.kernel import build_default_kernel
from plugin_agent.logging_config import configure_logging

app = typer.Typer(help="Pluginized Agent kernel v1")
console = Console()


def _kernel():
    return build_default_kernel()


@app.command()
def plugins() -> None:
    kernel = _kernel()
    table = Table("Plugin", "Version", "State", "Provides")
    for plugin in sorted(kernel.plugins.values(), key=lambda item: item.id):
        provides = ", ".join(cap.name for cap in plugin.descriptor_model.provides) or "-"
        table.add_row(plugin.id, plugin.descriptor_model.version, plugin.state.value, provides)
    console.print(table)


@app.command()
def capabilities() -> None:
    kernel = _kernel()
    table = Table("Capability", "Version", "Provider", "Input Schema", "Output Schema")
    for binding in kernel.capability_registry.list():
        table.add_row(
            binding.name,
            binding.version,
            binding.provider_plugin_id,
            binding.input_schema_ref or "-",
            binding.output_schema_ref or "-",
        )
    console.print(table)


@app.command()
def tools() -> None:
    kernel = _kernel()
    result = kernel.invoke("tool.registry.list", {}).payload
    table = Table("Tool", "Title", "Invoke Capability", "Input Schema")
    for tool in result["tools"]:
        table.add_row(tool["tool_id"], tool["title"], tool["invoke_capability"], tool["input_schema_ref"])
    console.print(table)


@app.command()
def invoke(capability: str, payload: str = typer.Option("{}", help="JSON payload")) -> None:
    kernel = _kernel()
    parsed = json.loads(payload)
    result = kernel.invoke(capability, parsed).payload
    console.print_json(data=result)


@app.command("inspect-agent")
def inspect_agent(agent_id: str, runtime_dir: str = typer.Option(".plugin-agent", help="Runtime directory")) -> None:
    assembly = AgentAssemblyService(runtime_dir=runtime_dir)
    runtime = assembly.agent_runtime(agent_id)
    console.print(f"Runtime status: {runtime['status']}")

    diagnostics_table = Table("Severity", "Code", "Capability", "Plugin", "Message")
    for diagnostic in runtime["diagnostics"]:
        diagnostics_table.add_row(
            diagnostic["severity"],
            diagnostic["code"],
            diagnostic.get("capability") or "-",
            diagnostic.get("plugin_instance_id") or diagnostic.get("plugin_id") or "-",
            diagnostic["message"],
        )
    if runtime["diagnostics"]:
        console.print(diagnostics_table)

    capability_table = Table("Capability", "Version", "Provider Instance", "Provider Package")
    for capability in runtime["capabilities"]:
        capability_table.add_row(
            capability["name"],
            capability["version"],
            capability["provider_instance_id"],
            capability["provider_plugin_id"],
        )
    console.print(capability_table)


@app.command()
def chat() -> None:
    kernel = _kernel()
    console.print("Plugin Agent chat. Type 'exit' to quit.")
    while True:
        message = typer.prompt("you")
        if message.strip().lower() in {"exit", "quit"}:
            break
        result = kernel.invoke("agent.run", {"message": message}).payload
        console.print(f"agent: {result['answer']}")


@app.command()
def serve(
    host: str = "127.0.0.1",
    port: int = 8000,
    log_level: str = typer.Option("INFO", "--log-level", envvar="PLUGIN_AGENT_LOG_LEVEL", help="Backend log level."),
    log_file: Optional[str] = typer.Option(None, "--log-file", envvar="PLUGIN_AGENT_LOG_FILE", help="Write backend logs to a file instead of stdout."),
) -> None:
    configure_logging(log_level, log_file=log_file)
    server = PluginAgentHTTPServer(state=create_app_state(), host=host, port=port)
    server.start()
    console.print(f"Plugin Agent HTTP service listening on {server.base_url}")
    try:
        while True:
            import time

            time.sleep(3600)
    except KeyboardInterrupt:
        server.stop()
        console.print("Plugin Agent HTTP service stopped")


def main() -> None:
    app()
