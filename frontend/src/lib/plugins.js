export const DEFAULT_PACKAGES = [
  'memory.file',
  'skill.registry',
  'model.openai_compatible',
  'tool.runtime',
  'tool.basic',
  'mcp.bridge',
  'agent.loop.react',
];

export const PACKAGE_CN = {
  'agent.loop.react': { name: 'ReAct 智能体循环', description: '基于模型推理、工具调用和记忆写入的智能体运行循环。' },
  'model.openai_compatible': { name: 'OpenAI 兼容模型', description: '调用兼容 OpenAI Chat Completions 的模型服务。' },
  'model.openrouter': { name: 'OpenRouter 模型', description: '通过 OpenRouter 的 OpenAI-compatible API 调用多家模型。' },
  'model.deepseek': { name: 'DeepSeek 模型', description: '通过 DeepSeek 的 OpenAI-compatible API 调用 DeepSeek 模型。' },
  'memory.file': { name: '文件记忆', description: '使用本地 JSONL 文件保存和检索智能体记忆。' },
  'skill.registry': { name: '技能注册表', description: '加载本地 SKILL.md 技能文件，并提供查询能力。' },
  'tool.runtime': { name: '工具运行时', description: '统一发现工具资源、校验参数并路由工具调用。' },
  'tool.basic': { name: '基础工具集', description: '内置 echo、当前时间和数字相加等基础工具。' },
  'context.compressor.summary': { name: '上下文摘要压缩', description: '将较长对话上下文压缩为简短摘要。' },
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

export function stripRedactedSecrets(value) {
  if (Array.isArray(value)) return value.map(stripRedactedSecrets);
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(
    Object.entries(value)
      .filter(([, item]) => item !== '********')
      .map(([key, item]) => [key, stripRedactedSecrets(item)]),
  );
}

function inferResource(plugin) {
  const id = plugin.package_id || plugin.id;
  const capabilityNames = (plugin.provides || []).map((capability) => capability.name);
  if (id === 'agent.loop.react' || capabilityNames.includes('agent.run')) return { kind: 'agent_loop', id: 'agent_loop', title: 'Agent Loop', description: '智能体运行循环', invoke_capability: 'agent.run' };
  if (id?.startsWith('model.') || capabilityNames.includes('model.chat')) return { kind: 'model', id: 'model', title: '模型', description: '模型对话能力', invoke_capability: 'model.chat' };
  if (id === 'memory.file' || capabilityNames.some((name) => name.startsWith('memory.'))) return { kind: 'memory', id: 'memory', title: '记忆', description: '记忆读写能力', invoke_capability: 'memory.query' };
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
