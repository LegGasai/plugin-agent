import json
import urllib.request
import zipfile
from pathlib import Path

from plugin_agent.kernel import AgentKernel
from plugin_agent.http_service import PluginAgentHTTPServer, create_app_state
from plugin_agent.plugin_store import load_installed_plugin_class
from plugin_agent_sdk import Plugin


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
        request_json(base, "POST", "/api/marketplace/install", {"package_id": "tool.versioned", "version": "0.2.0"})

        installed_packages = request_json(base, "GET", "/api/installed-plugin-packages")["plugin_packages"]
        installed_versions = {
            package["version"]
            for package in installed_packages
            if package["package_id"] == "tool.versioned" and package["source"] == "installed"
        }
        assert installed_versions == {"0.1.0", "0.2.0"}

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

        kernel = state.assembly.build_kernel_for_agent(created["id"])
        result = kernel.invoke("tool.invoke", {"tool_id": "versioned.answer", "arguments": {}}).payload

        assert result["result"] == "answer-from-0.1.0"
    finally:
        server.stop()


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
        "context.compressor.summary",
        "context.compressor.model",
    ]:
        assert market[package_id]["entrypoint"], package_id

    assert {cap["name"] for cap in market["agent.loop.react"]["provides"]} == {"agent.run", "agent.stream"}
    assert {cap["name"] for cap in market["skill.registry"]["provides"]} == {"skill.list", "skill.get", "skill.search"}
    assert "model.chat.stream" in {cap["name"] for cap in market["model.openai_compatible"]["provides"]}
    assert "model.chat.stream" in {cap["name"] for cap in market["model.openrouter"]["provides"]}
    assert "model.chat.stream" in {cap["name"] for cap in market["model.deepseek"]["provides"]}
    assert any(dep["capability"] == "model.chat" for dep in market["context.compressor.model"]["requires"])


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
        "context.compress",
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
