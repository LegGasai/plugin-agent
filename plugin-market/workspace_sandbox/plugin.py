from __future__ import annotations

from typing import Any

from plugin_agent_sdk import Plugin

from workspace_tools.bash import run_bash
from workspace_tools.context import WorkspaceContext
from workspace_tools.edit import edit_file
from workspace_tools.ls import list_directory
from workspace_tools.read import read_file
from workspace_tools.search import glob_files, grep_files
from workspace_tools.write import write_file


class WorkspaceSandboxPlugin(Plugin):
    def __init__(self, config: dict[str, Any] | None = None, instance_id: str | None = None) -> None:
        super().__init__(config, instance_id=instance_id)
        self.workspace = WorkspaceContext(self.config)

    def start(self, kernel: Any) -> None:
        super().start(kernel)
        self.workspace.start()

    def invoke(self, capability: str, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if capability == "workspace.ls":
            return {"result": list_directory(self.workspace, payload)}
        if capability == "workspace.read":
            return {"result": read_file(self.workspace, payload)}
        if capability == "workspace.write":
            return {"result": write_file(self.workspace, payload)}
        if capability == "workspace.edit":
            return {"result": edit_file(self.workspace, payload)}
        if capability == "workspace.grep":
            return {"result": grep_files(self.workspace, payload)}
        if capability == "workspace.glob":
            return {"result": glob_files(self.workspace, payload)}
        if capability == "workspace.bash":
            return {"result": run_bash(self.workspace, payload)}
        return super().invoke(capability, payload, context)
