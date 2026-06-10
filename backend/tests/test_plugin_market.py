import json
import platform
import shutil
import urllib.request
import zipfile
from pathlib import Path

import pytest

from plugin_agent.kernel import KernelInvokeError
from plugin_agent.kernel import AgentKernel
from plugin_agent.http_service import PluginAgentHTTPServer, create_app_state
from plugin_agent.plugin_store import load_installed_plugin_class
from plugin_agent_sdk import Plugin, PluginPackage


def request_json(base_url, method, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.loads(response.read().decode())


def request_multipart_upload(base_url, files):
    boundary = "----plugin-agent-test-boundary"
    body = bytearray()
    for filename, relative_path, content in files:
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="files"; filename="{filename}"\r\n'.encode())
        body.extend(b"Content-Type: application/octet-stream\r\n\r\n")
        body.extend(content)
        body.extend(b"\r\n")
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(b'Content-Disposition: form-data; name="relative_paths"\r\n\r\n')
        body.extend(relative_path.encode())
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        f"{base_url}/api/marketplace/upload",
        data=bytes(body),
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.loads(response.read().decode())


class CapturingModelPlugin(Plugin):
    descriptor = {
        "id": "model.capturing",
        "version": "1.0.0",
        "provides": [
            {
                "name": "model.chat",
                "version": "1.0.0",
                "input_schema_ref": "schema://model.chat.input.v1",
                "output_schema_ref": "schema://model.chat.output.v1",
            }
        ],
    }
    schemas = [
        {
            "schema_ref": "schema://model.chat.input.v1",
            "json_schema": {
                "type": "object",
                "required": ["messages", "tools"],
                "properties": {
                    "messages": {"type": "array"},
                    "tools": {"type": "array"},
                    "system_prompt": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        {
            "schema_ref": "schema://model.chat.output.v1",
            "json_schema": {
                "type": "object",
                "required": ["message"],
                "properties": {"message": {"type": "object"}, "raw": {}},
                "additionalProperties": False,
            },
        },
    ]

    def __init__(self):
        super().__init__()
        self.requests = []

    def invoke(self, capability, payload, context):
        if capability == "model.chat":
            self.requests.append(payload)
            return {"message": {"role": "assistant", "content": "模型生成的摘要", "tool_calls": []}, "raw": {}}
        return super().invoke(capability, payload, context)


def write_weather_plugin_package(tmp_path: Path) -> Path:
    source_dir = tmp_path / "weather-source"
    source_dir.mkdir()
    (source_dir / "plugin.yaml").write_text(
        """
id: tool.weather
version: 0.1.0
name: 天气工具
description: 返回指定城市的模拟天气。
categories: [tool]
runtime:
  type: python.in_process
  entrypoint: plugin.py:WeatherPlugin
provides:
  - name: tool.weather
    version: 1.0.0
    input_schema_ref: schema://tool.weather.input.v1
    output_schema_ref: schema://tool.weather.output.v1
resources:
  - kind: tool
    id: weather.lookup
    title: 天气查询
    description: 查询城市天气。
    invoke_capability: tool.weather
    schema_refs:
      input: schema://tool.weather.input.v1
      output: schema://tool.weather.output.v1
schemas:
  - schema_ref: schema://tool.weather.input.v1
    json_schema:
      type: object
      required: [city]
      additionalProperties: false
      properties:
        city:
          type: string
  - schema_ref: schema://tool.weather.output.v1
    json_schema:
      type: object
      required: [result]
      additionalProperties: false
      properties:
        result:
          type: object
""".strip()
    )
    (source_dir / "plugin.py").write_text(
        """
from plugin_agent_sdk import Plugin


class WeatherPlugin(Plugin):
    def invoke(self, capability, payload, context):
        if capability == "tool.weather":
            return {"result": {"city": payload["city"], "summary": "晴"}}
        return super().invoke(capability, payload, context)
""".strip()
    )
    package_path = tmp_path / "tool-weather-0.1.0.pluginpkg"
    with zipfile.ZipFile(package_path, "w") as archive:
        archive.write(source_dir / "plugin.yaml", "plugin.yaml")
        archive.write(source_dir / "plugin.py", "plugin.py")
    return package_path


def write_versioned_tool_package(tmp_path: Path, version: str, answer: str) -> Path:
    source_dir = tmp_path / f"versioned-source-{version}"
    source_dir.mkdir()
    (source_dir / "plugin.yaml").write_text(
        f"""
id: tool.versioned
version: {version}
name: 版本化工具
description: 用于验证插件实例可固定安装版本。
categories: [tool]
runtime:
  type: python.in_process
  entrypoint: plugin.py:VersionedToolPlugin
provides:
  - name: tool.versioned
    version: 1.0.0
    input_schema_ref: schema://tool.versioned.input.v1
    output_schema_ref: schema://tool.versioned.output.v1
resources:
  - kind: tool
    id: versioned.answer
    title: 版本化回答
    description: 返回当前插件版本的回答。
    invoke_capability: tool.versioned
    schema_refs:
      input: schema://tool.versioned.input.v1
      output: schema://tool.versioned.output.v1
schemas:
  - schema_ref: schema://tool.versioned.input.v1
    json_schema:
      type: object
      additionalProperties: false
      properties: {{}}
  - schema_ref: schema://tool.versioned.output.v1
    json_schema:
      type: object
      required: [result]
      additionalProperties: false
      properties:
        result:
          type: string
""".strip()
    )
    (source_dir / "plugin.py").write_text(
        f"""
from plugin_agent_sdk import Plugin


class VersionedToolPlugin(Plugin):
    def invoke(self, capability, payload, context):
        if capability == "tool.versioned":
            return {{"result": "{answer}"}}
        return super().invoke(capability, payload, context)
""".strip()
    )
    package_path = tmp_path / f"tool-versioned-{version}.pluginpkg"
    with zipfile.ZipFile(package_path, "w") as archive:
        archive.write(source_dir / "plugin.yaml", "plugin.yaml")
        archive.write(source_dir / "plugin.py", "plugin.py")
    return package_path


def write_multifile_tool_package(tmp_path: Path) -> Path:
    source_dir = tmp_path / "multifile-source"
    source_dir.mkdir()
    (source_dir / "plugin.yaml").write_text(
        """
id: tool.multifile
version: 0.1.0
name: 多文件工具
description: 验证外部插件可以拆分多个 Python 文件。
categories: [tool]
runtime:
  type: python.in_process
  entrypoint: plugin.py:MultifileToolPlugin
provides:
  - name: tool.multifile
    version: 1.0.0
    input_schema_ref: schema://tool.multifile.input.v1
    output_schema_ref: schema://tool.multifile.output.v1
resources:
  - kind: tool
    id: multifile.answer
    title: 多文件回答
    description: 通过 helper 模块返回回答。
    invoke_capability: tool.multifile
    schema_refs:
      input: schema://tool.multifile.input.v1
      output: schema://tool.multifile.output.v1
schemas:
  - schema_ref: schema://tool.multifile.input.v1
    json_schema:
      type: object
      additionalProperties: false
      properties: {}
  - schema_ref: schema://tool.multifile.output.v1
    json_schema:
      type: object
      required: [result]
      additionalProperties: false
      properties:
        result:
          type: string
""".strip()
    )
    (source_dir / "helper.py").write_text('VALUE = "from-helper"\n')
    (source_dir / "plugin.py").write_text(
        """
from helper import VALUE
from plugin_agent_sdk import Plugin


class MultifileToolPlugin(Plugin):
    def invoke(self, capability, payload, context):
        if capability == "tool.multifile":
            return {"result": VALUE}
        return super().invoke(capability, payload, context)
""".strip()
    )
    package_path = tmp_path / "tool-multifile-0.1.0.pluginpkg"
    with zipfile.ZipFile(package_path, "w") as archive:
        archive.write(source_dir / "plugin.yaml", "plugin.yaml")
        archive.write(source_dir / "plugin.py", "plugin.py")
        archive.write(source_dir / "helper.py", "helper.py")
    return package_path


def test_market_upload_install_and_runtime_loads_local_plugin(tmp_path):
    state = create_app_state(runtime_dir=tmp_path / "runtime", market_dir=tmp_path / "plugin-market")
    server = PluginAgentHTTPServer(state=state, host="127.0.0.1", port=0)
    server.start()
    try:
        base = server.base_url
        package_path = write_weather_plugin_package(tmp_path)

        uploaded = request_json(base, "POST", "/api/marketplace/upload", {"path": str(package_path)})
        assert uploaded["plugin_package"]["package_id"] == "tool.weather"
        assert uploaded["plugin_package"]["source"] == "market"
        assert Path(uploaded["market_path"]).exists()

        marketplace = request_json(base, "GET", "/api/marketplace/plugins")
        market_package = next(package for package in marketplace["market_plugin_packages"] if package["package_id"] == "tool.weather")
        assert market_package["installed"] is False

        installed = request_json(base, "POST", "/api/marketplace/install", {"package_id": "tool.weather"})
        assert installed["plugin_package"]["source"] == "installed"
        assert Path(installed["installed_path"]).exists()

        refreshed = request_json(base, "POST", "/api/plugin-packages/refresh")
        assert any(package["package_id"] == "tool.weather" and package["source"] == "installed" for package in refreshed["plugin_packages"])

        created = request_json(
            base,
            "POST",
            "/api/agents",
            {
                "name": "Weather Agent",
                "plugin_ids": ["tool.runtime", "tool.weather"],
            },
        )["agent"]
        resources = request_json(base, "GET", f"/api/agents/{created['id']}/resources")["resources"]
        assert any(resource["resource_id"] == "weather.lookup" for resource in resources)

        result = request_json(
            base,
            "POST",
            "/api/invoke",
            {
                "plugin_ids": ["tool.runtime", "tool.weather"],
                "capability": "tool.invoke",
                "payload": {"tool_id": "weather.lookup", "arguments": {"city": "杭州"}},
            },
        )
        assert result["tool_id"] == "weather.lookup"
        assert result["result"] == {"city": "杭州", "summary": "晴"}
    finally:
        server.stop()


def test_agent_instances_pin_installed_plugin_versions(tmp_path):
    state = create_app_state(runtime_dir=tmp_path / "runtime", market_dir=tmp_path / "plugin-market")
    server = PluginAgentHTTPServer(state=state, host="127.0.0.1", port=0)
    server.start()
    try:
        base = server.base_url
        first_package = write_versioned_tool_package(tmp_path, "0.1.0", "answer-from-0.1.0")
        second_package = write_versioned_tool_package(tmp_path, "0.2.0", "answer-from-0.2.0")
        request_json(base, "POST", "/api/marketplace/upload", {"path": str(first_package)})
        request_json(base, "POST", "/api/marketplace/upload", {"path": str(second_package)})
        request_json(base, "POST", "/api/marketplace/install", {"package_id": "tool.versioned", "version": "0.1.0"})

        created = request_json(
            base,
            "POST",
            "/api/agents",
            {
                "name": "Pinned Agent",
                "plugin_instances": [
                    {"package_id": "tool.runtime"},
                    {"package_id": "tool.versioned", "package_version": "0.1.0"},
                ],
            },
        )["agent"]
        versioned_instance = next(instance for instance in created["plugin_instances"] if instance["package_id"] == "tool.versioned")
        assert versioned_instance["package_version"] == "0.1.0"

        request_json(base, "POST", "/api/marketplace/install", {"package_id": "tool.versioned", "version": "0.2.0"})
        installed_packages = request_json(base, "GET", "/api/installed-plugin-packages")["plugin_packages"]
        installed_versions = [
            package["version"]
            for package in installed_packages
            if package["package_id"] == "tool.versioned" and package["source"] == "installed"
        ]
        assert installed_versions == ["0.2.0"]
        assert state.assembly.store.get_package("tool.versioned", "0.1.0")["source"] == "installed"

        kernel = state.assembly.build_kernel_for_agent(created["id"])
        result = kernel.invoke("tool.invoke", {"tool_id": "versioned.answer", "arguments": {}}).payload

        assert result["result"] == "answer-from-0.1.0"
    finally:
        server.stop()


def test_installing_new_plugin_version_replaces_unused_installed_version(tmp_path):
    state = create_app_state(runtime_dir=tmp_path / "runtime", market_dir=tmp_path / "plugin-market")
    first_package = write_versioned_tool_package(tmp_path, "0.1.0", "answer-from-0.1.0")
    second_package = write_versioned_tool_package(tmp_path, "0.2.0", "answer-from-0.2.0")
    state.assembly.reserve_upload({"path": str(first_package)})
    state.assembly.reserve_upload({"path": str(second_package)})

    first = state.assembly.install_market_plugin({"package_id": "tool.versioned", "version": "0.1.0"})
    assert Path(first["installed_path"]).exists()
    state.assembly.install_market_plugin({"package_id": "tool.versioned", "version": "0.2.0"})

    installed_versions = [
        package["version"]
        for package in state.assembly.list_installed_plugin_packages()
        if package["package_id"] == "tool.versioned" and package["source"] == "installed"
    ]
    assert installed_versions == ["0.2.0"]
    assert not Path(first["installed_path"]).exists()
    try:
        state.assembly.store.get_package("tool.versioned", "0.1.0")
    except KeyError:
        pass
    else:
        raise AssertionError("unused old installed plugin version should be removed")


def test_marketplace_marks_active_installed_version_and_newer_available(tmp_path):
    state = create_app_state(runtime_dir=tmp_path / "runtime", market_dir=tmp_path / "plugin-market")
    state.assembly.reserve_upload({"path": str(write_versioned_tool_package(tmp_path, "0.1.0", "answer-from-0.1.0"))})
    state.assembly.reserve_upload({"path": str(write_versioned_tool_package(tmp_path, "0.2.0", "answer-from-0.2.0"))})
    state.assembly.install_market_plugin({"package_id": "tool.versioned", "version": "0.1.0"})

    market = [
        package for package in state.assembly.marketplace()["market_plugin_packages"]
        if package["package_id"] == "tool.versioned"
    ]
    by_version = {package["version"]: package for package in market}

    assert set(by_version) == {"0.1.0", "0.2.0"}
    assert by_version["0.1.0"]["installed"] is True
    assert by_version["0.1.0"]["installed_version"] == "0.1.0"
    assert by_version["0.1.0"]["installed_source"] == "installed"
    assert by_version["0.1.0"]["latest_version"] == "0.2.0"
    assert by_version["0.1.0"]["has_newer_version"] is True
    assert by_version["0.1.0"]["update_available"] is True
    assert by_version["0.2.0"]["installed"] is False
    assert by_version["0.2.0"]["installed_version"] == "0.1.0"
    assert by_version["0.2.0"]["installed_source"] == "installed"
    assert by_version["0.2.0"]["latest_version"] == "0.2.0"
    assert by_version["0.2.0"]["has_newer_version"] is False
    assert by_version["0.2.0"]["update_available"] is True


def test_marketplace_marks_active_builtin_latest_version_as_installed(tmp_path):
    state = create_app_state(runtime_dir=tmp_path / "runtime")

    market_package = next(
        package for package in state.assembly.marketplace()["market_plugin_packages"]
        if package["package_id"] == "context.compressor.summary" and package["version"] == "1.1.0"
    )

    assert market_package["installed"] is True
    assert market_package["installed_version"] == "1.1.0"
    assert market_package["installed_source"] == "builtin"
    assert market_package["latest_version"] == "1.1.0"
    assert market_package["has_newer_version"] is False
    assert market_package["update_available"] is False


def test_default_package_selection_prefers_newer_builtin_over_older_installed(tmp_path):
    state = create_app_state(runtime_dir=tmp_path / "runtime")
    builtin_package = state.assembly.store.get_package("context.compressor.summary", "1.1.0")
    state.assembly.store.delete_package("context.compressor.summary", "1.1.0")
    old_package = {
        **builtin_package,
        "version": "1.0.0",
        "source": "installed",
        "installed_path": str(tmp_path / "old-installed-context-compressor"),
    }
    state.assembly.store.upsert_package(PluginPackage.model_validate(old_package))
    state.assembly.refresh_plugin_packages()

    selected = state.assembly.store.get_package("context.compressor.summary")

    assert selected["source"] == "builtin"
    assert selected["version"] == "1.1.0"


def test_installed_plugin_can_import_sibling_python_modules(tmp_path):
    state = create_app_state(runtime_dir=tmp_path / "runtime", market_dir=tmp_path / "plugin-market")
    package_path = write_multifile_tool_package(tmp_path)
    state.assembly.reserve_upload({"path": str(package_path)})
    state.assembly.install_market_plugin({"package_id": "tool.multifile"})

    kernel = state.assembly.build_kernel(["tool.runtime", "tool.multifile"])
    result = kernel.invoke("tool.invoke", {"tool_id": "multifile.answer", "arguments": {}}).payload

    assert result["result"] == "from-helper"


def test_installed_plugin_package_can_be_uninstalled(tmp_path):
    state = create_app_state(runtime_dir=tmp_path / "runtime", market_dir=tmp_path / "plugin-market")
    server = PluginAgentHTTPServer(state=state, host="127.0.0.1", port=0)
    server.start()
    try:
        base = server.base_url
        package_path = write_weather_plugin_package(tmp_path)
        request_json(base, "POST", "/api/marketplace/upload", {"path": str(package_path)})
        request_json(base, "POST", "/api/marketplace/install", {"package_id": "tool.weather"})

        installed_packages = request_json(base, "GET", "/api/installed-plugin-packages")["plugin_packages"]
        assert any(package["package_id"] == "tool.weather" and package["source"] == "installed" for package in installed_packages)

        result = request_json(base, "DELETE", "/api/installed-plugin-packages/tool.weather")

        assert result["uninstalled"] is True
        installed_packages = request_json(base, "GET", "/api/installed-plugin-packages")["plugin_packages"]
        assert not any(package["package_id"] == "tool.weather" for package in installed_packages)
        marketplace = request_json(base, "GET", "/api/marketplace/plugins")
        market_package = next(package for package in marketplace["market_plugin_packages"] if package["package_id"] == "tool.weather")
        assert market_package["installed"] is False
    finally:
        server.stop()


def test_market_upload_accepts_multipart_plugin_package_file(tmp_path):
    state = create_app_state(runtime_dir=tmp_path / "runtime", market_dir=tmp_path / "plugin-market")
    server = PluginAgentHTTPServer(state=state, host="127.0.0.1", port=0)
    server.start()
    try:
        package_path = write_weather_plugin_package(tmp_path)

        uploaded = request_multipart_upload(
            server.base_url,
            [(package_path.name, package_path.name, package_path.read_bytes())],
        )

        assert uploaded["plugin_package"]["package_id"] == "tool.weather"
        assert uploaded["plugin_package"]["source"] == "market"
        assert Path(uploaded["market_path"]).exists()
    finally:
        server.stop()


def test_market_upload_accepts_multipart_plugin_directory(tmp_path):
    state = create_app_state(runtime_dir=tmp_path / "runtime", market_dir=tmp_path / "plugin-market")
    server = PluginAgentHTTPServer(state=state, host="127.0.0.1", port=0)
    server.start()
    try:
        package_path = write_weather_plugin_package(tmp_path)
        with zipfile.ZipFile(package_path) as archive:
            files = [
                (Path(name).name, f"weather-plugin/{name}", archive.read(name))
                for name in archive.namelist()
            ]

        uploaded = request_multipart_upload(server.base_url, files)

        assert uploaded["plugin_package"]["package_id"] == "tool.weather"
        assert Path(uploaded["market_path"]).exists()
        marketplace = request_json(server.base_url, "GET", "/api/marketplace/plugins")
        assert any(package["package_id"] == "tool.weather" for package in marketplace["market_plugin_packages"])
    finally:
        server.stop()


def test_upload_rejects_invalid_plugin_package(tmp_path):
    state = create_app_state(runtime_dir=tmp_path / "runtime", market_dir=tmp_path / "plugin-market")
    bad_package = tmp_path / "bad.pluginpkg"
    with zipfile.ZipFile(bad_package, "w") as archive:
        archive.writestr("README.md", "missing manifest")

    result = state.assembly.validate_plugin({"path": str(bad_package)})

    assert result["valid"] is False
    assert "plugin.yaml is required" in result["errors"][0]


def test_unpackaged_plugin_directory_is_discovered_in_market(tmp_path):
    market_dir = tmp_path / "plugin-market"
    package_dir = market_dir / "tool-weather"
    package_dir.mkdir(parents=True)
    (package_dir / "plugin.yaml").write_text(
        """
id: tool.weather
version: 0.1.0
name: 天气工具
description: 返回指定城市的模拟天气。
runtime:
  type: python.in_process
  entrypoint: plugin.py:WeatherPlugin
provides:
  - name: tool.weather
    version: 1.0.0
resources:
  - kind: tool
    id: weather.lookup
    title: 天气查询
    invoke_capability: tool.weather
""".strip()
    )
    (package_dir / "plugin.py").write_text("from plugin_agent_sdk import Plugin\nclass WeatherPlugin(Plugin):\n    pass\n")
    state = create_app_state(runtime_dir=tmp_path / "runtime", market_dir=market_dir)

    marketplace = state.assembly.marketplace()

    market_package = next(package for package in marketplace["market_plugin_packages"] if package["package_id"] == "tool.weather")
    assert market_package["source"] == "market"
    assert market_package["installed"] is False
    assert not any(package["package_id"] == "tool.weather" for package in state.assembly.list_plugin_packages())


def test_project_plugin_market_contains_migrated_plugins(tmp_path):
    state = create_app_state(runtime_dir=tmp_path / "runtime")

    marketplace = state.assembly.marketplace()
    market_ids = {package["package_id"] for package in marketplace["market_plugin_packages"]}

    assert {
        "agent.loop.react",
        "mcp.bridge",
        "memory.file",
        "model.deepseek",
        "model.openai_compatible",
        "model.openrouter",
        "skill.registry",
        "tool.basic",
        "tool.runtime",
    }.issubset(market_ids)

    installed = state.assembly.install_market_plugin({"package_id": "tool.basic"})

    assert installed["plugin_package"]["source"] == "installed"
    assert installed["plugin_package"]["package_id"] == "tool.basic"
    assert any(package["package_id"] == "tool.basic" and package["source"] == "installed" for package in state.assembly.list_plugin_packages())


def test_installed_package_overrides_same_id_builtin_package(tmp_path):
    market_dir = tmp_path / "plugin-market"
    package_dir = market_dir / "tool-basic"
    package_dir.mkdir(parents=True)
    (package_dir / "plugin.yaml").write_text(
        """
descriptor:
  id: tool.basic
  version: 9.9.9
  name: 外部基础工具集
  description: 覆盖内置基础工具的外部插件。
  categories: [tool]
  provides:
    - name: tool.echo
      version: 1.0.0
      input_schema_ref: schema://tool.echo.input.v1
      output_schema_ref: schema://tool.echo.output.v1
runtime:
  type: python.in_process
  entrypoint: plugin.py:ExternalBasicToolPlugin
resources:
  - kind: tool
    id: echo
    title: External Echo
    description: External echo implementation.
    invoke_capability: tool.echo
    schema_refs:
      input: schema://tool.echo.input.v1
      output: schema://tool.echo.output.v1
schemas:
  - schema_ref: schema://tool.echo.input.v1
    json_schema:
      type: object
      required: [text]
      additionalProperties: false
      properties:
        text:
          type: string
  - schema_ref: schema://tool.echo.output.v1
    json_schema:
      type: object
      required: [result]
      additionalProperties: false
      properties:
        result:
          type: string
""".strip()
    )
    (package_dir / "plugin.py").write_text(
        """
from plugin_agent_sdk import Plugin


class ExternalBasicToolPlugin(Plugin):
    def invoke(self, capability, payload, context):
        if capability == "tool.echo":
            return {"result": "external:" + payload["text"]}
        return super().invoke(capability, payload, context)
""".strip()
    )

    state = create_app_state(runtime_dir=tmp_path / "runtime", market_dir=market_dir)
    state.assembly.install_market_plugin({"package_id": "tool.basic"})

    result = state.assembly.build_kernel(["tool.runtime", "tool.basic"]).invoke("tool.invoke", {"tool_id": "echo", "arguments": {"text": "hi"}}).payload

    assert result["result"] == "external:hi"


def test_project_market_plugins_expose_latest_runtime_contracts(tmp_path):
    state = create_app_state(runtime_dir=tmp_path / "runtime")

    market = {
        package["package_id"]: package
        for package in state.assembly.marketplace()["market_plugin_packages"]
    }

    for package_id in [
        "agent.loop.react",
        "mcp.bridge",
        "memory.file",
        "model.deepseek",
        "model.openai_compatible",
        "model.openrouter",
        "skill.registry",
        "tool.basic",
        "tool.runtime",
        "context.manager",
        "workspace.sandbox",
        "context.compressor.summary",
        "context.compressor.model",
    ]:
        assert market[package_id]["entrypoint"], package_id

    assert {cap["name"] for cap in market["agent.loop.react"]["provides"]} == {"agent.run", "agent.stream"}
    assert {cap["name"] for cap in market["skill.registry"]["provides"]} == {"skill.list", "skill.get", "skill.search"}
    assert "model.chat.stream" in {cap["name"] for cap in market["model.openai_compatible"]["provides"]}
    assert "model.chat.stream" in {cap["name"] for cap in market["model.openrouter"]["provides"]}
    assert "model.chat.stream" in {cap["name"] for cap in market["model.deepseek"]["provides"]}
    assert {cap["name"] for cap in market["context.manager"]["provides"]} == {"context.compress"}
    assert any(dep["capability"] == "context.compressor.compress" for dep in market["context.manager"]["requires"])
    assert any(dep["capability"] == "model.chat" for dep in market["context.compressor.model"]["requires"])
    assert {cap["name"] for cap in market["context.compressor.model"]["provides"]} == {"context.compressor.compress"}
    assert {cap["name"] for cap in market["workspace.sandbox"]["provides"]} == {
        "workspace.ls",
        "workspace.read",
        "workspace.write",
        "workspace.edit",
        "workspace.grep",
        "workspace.glob",
        "workspace.bash",
    }


def test_workspace_sandbox_tools_are_invoked_through_tool_runtime(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("hello sandbox\nsecond line\n")
    (workspace / "src").mkdir()
    (workspace / "src" / "app.py").write_text("print('hello')\n")
    (workspace / ".env").write_text("SECRET=1\n")
    state = create_app_state(runtime_dir=tmp_path / "runtime")
    state.assembly.install_market_plugin({"package_id": "workspace.sandbox"})
    kernel = state.assembly.build_kernel(
        ["tool.runtime", "workspace.sandbox"],
        {
            "workspace.sandbox": {
                "workspace_root": str(workspace),
                "sandbox": {"enabled": False, "allowed_commands": ["python *"]},
            }
        },
    )

    def invoke(tool_id, arguments):
        return kernel.invoke("tool.invoke", {"tool_id": tool_id, "arguments": arguments}).payload["result"]

    listed = invoke("workspace.ls", {"path": ".", "recursive": True})
    assert listed["ok"] is True
    assert "README.md" in listed["entries"]
    assert ".env" not in listed["entries"]

    read = invoke("workspace.read", {"path": "README.md", "limit": 1})
    assert read["ok"] is True
    assert read["content"] == "1: hello sandbox"

    written = invoke("workspace.write", {"path": "notes/todo.txt", "content": "ship it\n"})
    assert written["ok"] is True
    assert (workspace / "notes" / "todo.txt").read_text() == "ship it\n"

    edited = invoke(
        "workspace.edit",
        {"file_path": "README.md", "old_string": "hello sandbox", "new_string": "hello workspace"},
    )
    assert edited["ok"] is True
    assert (workspace / "README.md").read_text().startswith("hello workspace")

    grep = invoke("workspace.grep", {"pattern": "hello", "path": ".", "include": "*.md"})
    assert grep["ok"] is True
    assert any(match["path"] == "README.md" for match in grep["matches"])

    glob = invoke("workspace.glob", {"pattern": "**/*.py"})
    assert glob["ok"] is True
    assert glob["matches"] == ["src/app.py"]

    bash = invoke("workspace.bash", {"command": "python -c 'print(123)'"})
    assert bash["ok"] is True
    assert bash["exit_code"] == 0
    assert bash["stdout"].strip() == "123"


def test_workspace_sandbox_rejects_path_escape_and_protected_writes(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside")
    (workspace / ".git").mkdir()
    state = create_app_state(runtime_dir=tmp_path / "runtime")
    state.assembly.install_market_plugin({"package_id": "workspace.sandbox"})
    kernel = state.assembly.build_kernel(
        ["tool.runtime", "workspace.sandbox"],
        {"workspace.sandbox": {"workspace_root": str(workspace), "sandbox": {"enabled": False}}},
    )

    with pytest.raises(KernelInvokeError, match="outside workspace"):
        kernel.invoke("tool.invoke", {"tool_id": "workspace.read", "arguments": {"path": "../outside.txt"}})

    with pytest.raises(KernelInvokeError, match="protected path"):
        kernel.invoke("tool.invoke", {"tool_id": "workspace.write", "arguments": {"path": ".git/config", "content": "bad"}})


def test_workspace_sandbox_bash_policy_and_timeout(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state = create_app_state(runtime_dir=tmp_path / "runtime")
    state.assembly.install_market_plugin({"package_id": "workspace.sandbox"})
    kernel = state.assembly.build_kernel(
        ["tool.runtime", "workspace.sandbox"],
        {
            "workspace.sandbox": {
                "workspace_root": str(workspace),
                "sandbox": {
                    "enabled": False,
                    "allowed_commands": ["python *"],
                    "denied_patterns": ["python *forbidden*"],
                    "command_timeout_ms": 200,
                },
            }
        },
    )

    with pytest.raises(KernelInvokeError, match="not allowed"):
        kernel.invoke("tool.invoke", {"tool_id": "workspace.bash", "arguments": {"command": "echo nope"}})

    with pytest.raises(KernelInvokeError, match="denied"):
        kernel.invoke("tool.invoke", {"tool_id": "workspace.bash", "arguments": {"command": "python -c 'print(\"forbidden\")'"}})

    result = kernel.invoke(
        "tool.invoke",
        {"tool_id": "workspace.bash", "arguments": {"command": "python -c 'import time; time.sleep(1)'", "timeout_ms": 100}},
    ).payload["result"]
    assert result["timed_out"] is True
    assert result["exit_code"] is None


@pytest.mark.skipif(platform.system() != "Darwin" or not shutil.which("sandbox-exec"), reason="macOS sandbox-exec only")
def test_workspace_sandbox_seatbelt_blocks_writes_outside_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    state = create_app_state(runtime_dir=tmp_path / "runtime")
    state.assembly.install_market_plugin({"package_id": "workspace.sandbox"})
    kernel = state.assembly.build_kernel(
        ["tool.runtime", "workspace.sandbox"],
        {
            "workspace.sandbox": {
                "workspace_root": str(workspace),
                "sandbox": {"enabled": True, "allowed_commands": ["python *"], "network_access": False},
            }
        },
    )

    result = kernel.invoke(
        "tool.invoke",
        {
            "tool_id": "workspace.bash",
            "arguments": {"command": f"python -c 'from pathlib import Path; Path({str(outside)!r}).write_text(\"bad\")'"},
        },
    ).payload["result"]

    assert result["sandbox_backend"] == "seatbelt"
    assert result["exit_code"] != 0
    assert not outside.exists()


def test_model_context_compressor_uses_model_chat_provider_from_market_plugin(tmp_path):
    state = create_app_state(runtime_dir=tmp_path / "runtime")
    installed = state.assembly.install_market_plugin({"package_id": "context.compressor.model"})
    plugin_class = load_installed_plugin_class(installed["installed_path"], installed["plugin_package"]["entrypoint"])
    compressor = plugin_class({"max_summary_chars": 800})
    model = CapturingModelPlugin()
    kernel = AgentKernel()
    kernel.load_plugins([model, compressor])
    kernel.start_all()

    result = kernel.invoke(
        "context.compressor.compress",
        {
            "messages": [
                {"role": "user", "content": "第一轮问题"},
                {"role": "assistant", "content": "第一轮回答"},
            ]
        },
    ).payload

    assert result["summary"] == "模型生成的摘要"
    assert model.requests
    assert "第一轮问题" in model.requests[0]["messages"][0]["content"]
    assert "compact" in model.requests[0]["system_prompt"].lower()
