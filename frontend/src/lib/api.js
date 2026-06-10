import { selectDefaultPackageVersions } from './plugins.js';

export const API_BASE = import.meta.env.VITE_PLUGIN_AGENT_API || 'http://127.0.0.1:8000';

export async function api(path, options = {}) {
  const headers = options.body instanceof FormData
    ? { ...(options.headers || {}) }
    : { 'Content-Type': 'application/json', ...(options.headers || {}) };
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

export async function loadInstalledPluginPackages(tag = '') {
  const query = tag ? `?tag=${encodeURIComponent(tag)}` : '';
  return api(`/api/installed-plugin-packages${query}`);
}

export async function loadPluginPackages(tag = '') {
  const query = tag ? `?tag=${encodeURIComponent(tag)}` : '';
  return api(`/api/plugin-packages${query}`);
}

export async function loadMarketplace(tag = '') {
  const query = tag ? `?tag=${encodeURIComponent(tag)}` : '';
  return api(`/api/marketplace/plugins${query}`);
}

export async function uploadMarketPlugin(path) {
  if (typeof path !== 'string') {
    const formData = new FormData();
    Array.from(path).forEach((file) => {
      formData.append('files', file, file.name);
      formData.append('relative_paths', file.webkitRelativePath || file.name);
    });
    return api('/api/marketplace/upload', {
      method: 'POST',
      body: formData,
    });
  }
  return api('/api/marketplace/upload', {
    method: 'POST',
    body: JSON.stringify({ path }),
  });
}

export async function installMarketPlugin(packageId, version) {
  return api('/api/marketplace/install', {
    method: 'POST',
    body: JSON.stringify({ package_id: packageId, version }),
  });
}

export async function uninstallInstalledPlugin(packageId, version) {
  const query = version ? `?version=${encodeURIComponent(version)}` : '';
  return api(`/api/installed-plugin-packages/${encodeURIComponent(packageId)}${query}`, {
    method: 'DELETE',
  });
}

export async function loadBootstrapData() {
  const [packageData, marketData, agentData] = await Promise.all([
    loadInstalledPluginPackages().catch(() => loadPluginPackages().catch(() => null)),
    loadMarketplace(),
    api('/api/agents'),
  ]);
  return { packageData, marketData, agentData };
}

export async function loadAgentRuntime(agentId) {
  const [detailData, runtimeData] = await Promise.all([
    api(`/api/agents/${agentId}`),
    api(`/api/agents/${agentId}/runtime`).catch(() => null),
  ]);
  if (runtimeData) {
    return {
      agent: detailData.agent,
      resources: runtimeData.resources || [],
      capabilities: runtimeData.capabilities || [],
      diagnostics: runtimeData.diagnostics || [],
      runtimeStatus: runtimeData.status || 'ready',
      capabilityBindings: runtimeData.capability_bindings || {},
      capabilityCandidates: runtimeData.capability_candidates || [],
      startupOrder: runtimeData.startup_order || [],
    };
  }
  const [resourceData, capabilityData] = await Promise.all([
    api(`/api/agents/${agentId}/resources`).catch(() => ({ resources: [] })),
    api(`/api/agents/${agentId}/capabilities`).catch(() => ({ capabilities: [] })),
  ]);
  return {
    agent: detailData.agent,
    resources: resourceData.resources || [],
    capabilities: capabilityData.capabilities || [],
    diagnostics: [],
    runtimeStatus: 'ready',
    capabilityBindings: {},
    capabilityCandidates: [],
    startupOrder: [],
  };
}

export async function loadAgentSessions(agentId) {
  return api(`/api/agents/${encodeURIComponent(agentId)}/sessions`);
}

export async function createAgentSession(agentId, title = '') {
  return api(`/api/agents/${encodeURIComponent(agentId)}/sessions`, {
    method: 'POST',
    body: JSON.stringify({ title }),
  });
}

export async function loadSessionMessages(sessionId) {
  return api(`/api/sessions/${encodeURIComponent(sessionId)}/messages`);
}

export async function deleteAgentSession(sessionId) {
  return api(`/api/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'DELETE',
  });
}

export async function updateAgent(agentId, payload) {
  return api(`/api/agents/${agentId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export async function updateAgentCapabilityBindings(agentId, capabilityBindings) {
  return api(`/api/agents/${encodeURIComponent(agentId)}/capability-bindings`, {
    method: 'PUT',
    body: JSON.stringify({ capability_bindings: capabilityBindings }),
  });
}

export async function streamAgentRun(agentId, sessionId, message, onEvent) {
  const response = await fetch(`${API_BASE}/api/agents/${encodeURIComponent(agentId)}/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error || response.statusText);
  }
  if (!response.body) throw new Error('当前浏览器不支持流式响应');

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split('\n\n');
    buffer = chunks.pop() || '';
    if (emitSseChunks(chunks, onEvent)) {
      await reader.cancel();
      return;
    }
  }
  if (buffer.trim()) emitSseChunk(buffer, onEvent);
}

function emitSseChunk(chunk, onEvent) {
  const dataLine = chunk.split('\n').find((line) => line.startsWith('data: '));
  if (!dataLine) return;
  const event = JSON.parse(dataLine.slice('data: '.length));
  onEvent(event);
  return event.type === 'run_completed' || event.type === 'run_failed';
}

function emitSseChunks(chunks, onEvent) {
  return chunks.some((chunk) => emitSseChunk(chunk, onEvent));
}

export function createDefaultAgentPayload(name, description, packages, packageIds, configs) {
  const defaultPackages = selectDefaultPackageVersions(packages);
  const pluginInstances = packageIds.map((packageId) => {
    const pluginPackage = defaultPackages.find((item) => item.package_id === packageId);
    return {
      package_id: packageId,
      package_version: pluginPackage?.version,
      display_name: pluginPackage?.name || packageId,
      config: configs[packageId] || {},
    };
  });
  return {
    name,
    description,
    plugin_ids: packageIds,
    configs,
    plugin_instances: pluginInstances,
  };
}
