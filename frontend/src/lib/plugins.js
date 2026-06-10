export const DEFAULT_PACKAGES = [
  'memory.file',
  'skill.registry',
  'model.deepseek',
  'tool.runtime',
  'tool.basic',
  'context.compressor.summary',
  'context.manager',
  'mcp.bridge',
  'agent.loop.react',
];

export const PACKAGE_CN = {
  'agent.loop.react': { name: 'ReAct 智能体循环', description: '基于模型推理、工具调用和 Markdown 记忆索引的智能体运行循环。' },
  'agent.loop.codex_bridge': { name: 'Codex Bridge', description: '通过本地 codex exec 运行任务，并桥接为 Agent 流式输出。' },
  'agent.loop.claude_code_bridge': { name: 'Claude Code Bridge', description: '通过本地 claude --print 运行任务，并桥接为 Agent 流式输出。' },
  'model.openai_compatible': { name: 'OpenAI 兼容模型', description: '调用兼容 OpenAI Chat Completions 的模型服务。' },
  'model.openrouter': { name: 'OpenRouter 模型', description: '通过 OpenRouter 的 OpenAI-compatible API 调用多家模型。' },
  'model.deepseek': { name: 'DeepSeek 模型', description: '通过 DeepSeek 的 OpenAI-compatible API 调用 DeepSeek 模型。' },
  'memory.file': { name: '文件记忆', description: '使用 MEMORY.md 和 Markdown 文件保存智能体记忆。' },
  'skill.registry': { name: '技能注册表', description: '加载本地 SKILL.md 技能文件，并提供列表、激活和文件读取能力。' },
  'tool.runtime': { name: '工具运行时', description: '统一发现工具资源、校验参数并路由工具调用。' },
  'tool.basic': { name: '基础工具集', description: '内置 echo、当前时间和数字相加等基础工具。' },
  'context.manager': { name: '上下文管理器', description: '通过插件能力编排上下文压缩和消息替换。' },
  'context.compressor.summary': { name: '上下文摘要压缩', description: '将较长对话上下文压缩为简短摘要。' },
  'workspace.sandbox': { name: '代码沙盒', description: '在隔离的代码沙盒内提供文件读写、搜索和沙箱命令执行工具。' },
  'mcp.bridge': { name: 'MCP 桥接器', description: '将 stdio MCP 服务中的工具桥接到智能体工具系统。' },
};

export const KIND_LABELS = {
  agent_loop: 'Agent Loop',
  model: '模型',
  memory: '记忆',
  skill: '技能',
  tool: '工具',
  tool_runtime: '工具运行时',
  context: '上下文',
  mcp_server: 'MCP',
  extension: '扩展',
};

export function normalizePackage(plugin) {
  const packageId = plugin.package_id || plugin.id;
  const resources = plugin.resources?.length ? plugin.resources : [inferResource(plugin)];
  const cn = PACKAGE_CN[packageId] || {};
  return {
    package_id: packageId,
    id: packageId,
    name: cn.name || plugin.name || packageId,
    version: plugin.version || '1.0.0',
    description: cn.description || plugin.description || `${packageId} 插件包`,
    runtime: plugin.runtime || { type: 'python.in_process' },
    source: plugin.source || 'builtin',
    installed: Boolean(plugin.installed),
    installed_version: plugin.installed_version || null,
    installed_source: plugin.installed_source || null,
    latest_version: plugin.latest_version || null,
    has_newer_version: Boolean(plugin.has_newer_version),
    update_available: Boolean(plugin.update_available),
    market_path: plugin.market_path,
    installed_path: plugin.installed_path,
    categories: uniqueItems(plugin.categories || []),
    tags: uniqueItems(plugin.tags || []),
    resources,
    provides: plugin.provides || [],
    requires: plugin.requires || [],
    config_schema_ref: plugin.config_schema_ref,
    schemas: plugin.schemas || [],
    manifest_path: plugin.manifest_path,
  };
}

export function packageKinds(pluginPackage) {
  return uniqueItems((pluginPackage.resources || []).map((resource) => resource.kind));
}

export function hasKind(pluginPackage, kind) {
  return packageKinds(pluginPackage).includes(kind);
}

export function resourceLabel(kind) {
  return KIND_LABELS[kind] || kind;
}

export function runtimeLabel(type) {
  if (!type || type === 'python.in_process') return '本地插件';
  return type;
}

export function pluginDisplayTags(pluginPackage) {
  return uniqueItems([
    ...packageKinds(pluginPackage).map(resourceLabel),
    ...(pluginPackage.tags || []),
  ]);
}

export function selectDefaultPackageVersions(packages) {
  const byId = new Map();
  for (const pluginPackage of packages) {
    const current = byId.get(pluginPackage.package_id);
    if (!current || comparePackageDefault(pluginPackage, current) > 0) {
      byId.set(pluginPackage.package_id, pluginPackage);
    }
  }
  return Array.from(byId.values());
}

export function stripRedactedSecrets(value) {
  if (Array.isArray(value)) return value.map(stripRedactedSecrets);
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(
    Object.entries(value)
      .filter(([, item]) => item !== '********')
      .map(([key, item]) => [key, stripRedactedSecrets(item)]),
  );
}

function comparePackageDefault(left, right) {
  const versionCompare = String(left.version || '').localeCompare(String(right.version || ''), undefined, { numeric: true });
  if (versionCompare !== 0) return versionCompare;
  const sourceRank = (pluginPackage) => (pluginPackage.source === 'installed' ? 1 : 0);
  return sourceRank(left) - sourceRank(right);
}

function inferResource(plugin) {
  const id = plugin.package_id || plugin.id;
  const capabilityNames = (plugin.provides || []).map((capability) => capability.name);
  if (id === 'agent.loop.react' || capabilityNames.includes('agent.run')) return { kind: 'agent_loop', id: 'agent_loop', title: 'Agent Loop', description: '智能体运行循环', invoke_capability: 'agent.run' };
  if (id?.startsWith('model.') || capabilityNames.includes('model.chat')) return { kind: 'model', id: 'model', title: '模型', description: '模型对话能力', invoke_capability: 'model.chat' };
  if (id === 'memory.file' || capabilityNames.some((name) => name.startsWith('memory.'))) return { kind: 'memory', id: 'memory', title: '记忆', description: '记忆读写能力', invoke_capability: 'memory.read' };
  if (id === 'skill.registry' || capabilityNames.some((name) => name.startsWith('skill.'))) return { kind: 'skill', id: 'skill', title: '技能', description: '技能注册表', invoke_capability: 'skill.list' };
  if (id === 'mcp.bridge' || capabilityNames.some((name) => name.startsWith('mcp.'))) return { kind: 'mcp_server', id: 'mcp', title: 'MCP 桥接', description: 'MCP 工具桥接', invoke_capability: 'mcp.tool.call' };
  if (id === 'tool.runtime') return { kind: 'tool_runtime', id: 'tool_runtime', title: '工具运行时', description: '工具发现与调用', invoke_capability: 'tool.invoke' };
  if (id === 'context.compressor.summary' || capabilityNames.some((name) => name.startsWith('context.'))) return { kind: 'context', id: 'context', title: '上下文', description: '上下文压缩能力', invoke_capability: 'context.compress' };
  if (capabilityNames.some((name) => name.startsWith('tool.'))) return { kind: 'tool', id, title: plugin.name || id, description: plugin.description || '工具插件' };
  return { kind: 'extension', id, title: plugin.name || id, description: plugin.description || '扩展插件' };
}

function uniqueItems(items) {
  const seen = new Set();
  return items.filter((item) => {
    if (!item || seen.has(item)) return false;
    seen.add(item);
    return true;
  });
}
