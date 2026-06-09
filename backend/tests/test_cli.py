
import json

from typer.testing import CliRunner

from plugin_agent.assembly import AgentAssemblyService
from plugin_agent.cli import app


def test_cli_lists_plugins_capabilities_tools_and_invokes_tool():
    runner = CliRunner()

    assert runner.invoke(app, ["plugins"]).exit_code == 0
    assert "agent.loop.react" in runner.invoke(app, ["plugins"]).stdout
    assert "tool.invoke" in runner.invoke(app, ["capabilities"]).stdout
    assert "math.add" in runner.invoke(app, ["tools"]).stdout

    payload = json.dumps({"tool_id": "math.add", "arguments": {"a": 4, "b": 5}})
    result = runner.invoke(app, ["invoke", "tool.invoke", "--payload", payload])

    assert result.exit_code == 0
    assert "9" in result.stdout


def test_cli_inspects_saved_agent_runtime(tmp_path):
    runner = CliRunner()
    runtime_dir = tmp_path / ".plugin-agent"

    assembly = AgentAssemblyService(runtime_dir=runtime_dir)
    agent = assembly.create_agent(
        "CLI Agent",
        plugin_ids=["memory.file", "skill.registry", "model.openai_compatible", "tool.runtime", "tool.basic", "agent.loop.react"],
        configs={"model.openai_compatible": {"api_key": "test-key"}},
    )

    result = runner.invoke(app, ["inspect-agent", agent["id"], "--runtime-dir", str(runtime_dir)])

    assert result.exit_code == 0
    assert "ready" in result.stdout
    assert "agent.run" in result.stdout
