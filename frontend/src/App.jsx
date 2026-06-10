import { useEffect, useMemo, useRef, useState } from 'react';
import { Bot, Boxes, MessageSquare, Store } from 'lucide-react';
import {
  api,
  API_BASE,
  createAgentSession,
  createDefaultAgentPayload,
  deleteAgentSession,
  loadAgentRuntime,
  loadAgentSessions,
  loadBootstrapData,
  loadSessionMessages,
  streamAgentRun,
  updateAgent as updateAgentRequest,
  updateAgentCapabilityBindings,
} from './lib/api.js';
import { DEFAULT_PACKAGES, normalizePackage } from './lib/plugins.js';
import { ConfirmDialog } from './components/ConfirmDialog.jsx';
import { NotificationToast } from './components/NotificationToast.jsx';
import { AgentSquarePage } from './pages/AgentSquarePage.jsx';
import { MarketPage } from './pages/MarketPage.jsx';
import { WorkbenchPage } from './pages/WorkbenchPage.jsx';

const DEFAULT_VIEW = 'square';
const VIEW_IDS = new Set(['market', 'square', 'workbench']);
const ACTIVE_AGENT_STORAGE_KEY = 'plugin-agent.activeAgentId';
const WELCOME_MESSAGE = {
  id: 'welcome',
  role: 'assistant',
  content: '你好，我是由插件实例组装的 Agent。左侧维护插件配置与运行资源，右侧负责对话和工具调用。',
};

function readViewFromUrl() {
  if (typeof window === 'undefined') return DEFAULT_VIEW;
  const pathView = window.location.pathname.replace(/^\/+|\/+$/g, '');
  if (VIEW_IDS.has(pathView)) return pathView;
  const hashView = window.location.hash.replace(/^#\/?/, '');
  return VIEW_IDS.has(hashView) ? hashView : DEFAULT_VIEW;
}

function routeForView(view) {
  return `/${view}`;
}

function readStoredActiveAgentId() {
  if (typeof window === 'undefined') return '';
  try {
    return window.localStorage.getItem(ACTIVE_AGENT_STORAGE_KEY) || '';
  } catch {
    return '';
  }
}

function writeStoredActiveAgentId(agentId) {
  if (typeof window === 'undefined') return;
  try {
    if (agentId) {
      window.localStorage.setItem(ACTIVE_AGENT_STORAGE_KEY, agentId);
    } else {
      window.localStorage.removeItem(ACTIVE_AGENT_STORAGE_KEY);
    }
  } catch {
    // Ignore storage errors so private-mode or quota failures do not block the console.
  }
}

export default function App() {
  const [view, setViewState] = useState(readViewFromUrl);
  const [packages, setPackages] = useState([]);
  const [agents, setAgents] = useState([]);
  const [activeAgentId, setActiveAgentIdState] = useState(readStoredActiveAgentId);
  const [agentDetails, setAgentDetails] = useState(null);
  const [resources, setResources] = useState([]);
  const [capabilities, setCapabilities] = useState([]);
  const [capabilityCandidates, setCapabilityCandidates] = useState([]);
  const [capabilityBindings, setCapabilityBindings] = useState({});
  const [diagnostics, setDiagnostics] = useState([]);
  const [runtimeStatus, setRuntimeStatus] = useState('ready');
  const [sessions, setSessions] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState('');
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [messages, setMessages] = useState([WELCOME_MESSAGE]);
  const [status, setStatus] = useState('就绪');
  const [error, setError] = useState('');
  const [toast, setToast] = useState(null);
  const [isRunning, setIsRunning] = useState(false);
  const [pendingDeleteAgent, setPendingDeleteAgent] = useState(null);
  const [pendingDeleteSession, setPendingDeleteSession] = useState(null);
  const activeAgentIdRef = useRef(activeAgentId);
  const activeSessionIdRef = useRef(activeSessionId);

  useEffect(() => { refresh(); }, []);
  useEffect(() => { activeAgentIdRef.current = activeAgentId; }, [activeAgentId]);
  useEffect(() => { activeSessionIdRef.current = activeSessionId; }, [activeSessionId]);
  useEffect(() => {
    const syncViewFromUrl = () => {
      const nextView = readViewFromUrl();
      setViewState(nextView);
      if (window.location.hash) {
        window.history.replaceState({}, '', routeForView(nextView));
      }
    };
    syncViewFromUrl();
    window.addEventListener('popstate', syncViewFromUrl);
    return () => window.removeEventListener('popstate', syncViewFromUrl);
  }, []);
  useEffect(() => {
    setIsRunning(false);
    if (activeAgentId) {
      refreshAgentRuntime(activeAgentId);
      refreshAgentSessions(activeAgentId);
    } else {
      setSessions([]);
      setActiveSessionId('');
      setMessages([WELCOME_MESSAGE]);
    }
  }, [activeAgentId]);

  function setActiveAgentId(nextAgentId) {
    setActiveAgentIdState((current) => {
      const value = typeof nextAgentId === 'function' ? nextAgentId(current) : nextAgentId;
      writeStoredActiveAgentId(value || '');
      return value || '';
    });
  }

  function setView(nextView) {
    const normalizedView = VIEW_IDS.has(nextView) ? nextView : DEFAULT_VIEW;
    setViewState(normalizedView);
    const nextPath = routeForView(normalizedView);
    if (window.location.pathname !== nextPath || window.location.hash) {
      window.history.pushState({}, '', nextPath);
    }
  }

  async function refresh() {
    setStatus('正在加载工作台');
    setError('');
    try {
      const { packageData, agentData } = await loadBootstrapData();
      const rawPackages = packageData?.plugin_packages || [];
      const normalized = rawPackages.map(normalizePackage);
      const nextAgents = agentData.agents || [];
      setPackages(normalized);
      setAgents(nextAgents);
      if (nextAgents[0]) {
        setActiveAgentId((current) => {
          const currentExists = current && nextAgents.some((agent) => agent.id === current);
          if (currentExists) return current;
          const stored = readStoredActiveAgentId();
          const storedExists = stored && nextAgents.some((agent) => agent.id === stored);
          return storedExists ? stored : nextAgents[0].id;
        });
      } else {
        setActiveAgentId('');
        setAgentDetails(null);
        setResources([]);
        setCapabilities([]);
        setCapabilityCandidates([]);
        setCapabilityBindings({});
        setDiagnostics([]);
        setRuntimeStatus('ready');
        setSessions([]);
        setActiveSessionId('');
        setMessages([WELCOME_MESSAGE]);
      }
      setStatus(packageData ? '就绪' : '已兼容旧版后端数据');
    } catch (event) {
      setError(`加载失败：${event.message}`);
      setStatus('加载失败');
    }
  }

  async function refreshAgentRuntime(agentId = activeAgentId) {
    if (!agentId) return;
    try {
      const data = await loadAgentRuntime(agentId);
      if (activeAgentIdRef.current !== agentId) return;
      setAgentDetails(data.agent);
      setResources(data.resources);
      setCapabilities(data.capabilities);
      setCapabilityCandidates(data.capabilityCandidates || []);
      setCapabilityBindings(data.capabilityBindings || {});
      setDiagnostics(data.diagnostics || []);
      setRuntimeStatus(data.runtimeStatus || 'ready');
    } catch (event) {
      if (activeAgentIdRef.current !== agentId) return;
      setError(`读取智能体失败：${event.message}`);
    }
  }

  async function refreshAgentSessions(agentId = activeAgentId, preferredSessionId = activeSessionId) {
    if (!agentId) return;
    setSessionsLoading(true);
    try {
      const data = await loadAgentSessions(agentId);
      if (activeAgentIdRef.current !== agentId) return;
      const nextSessions = data.sessions || [];
      setSessions(nextSessions);
      const nextSessionId = preferredSessionId && nextSessions.some((session) => session.id === preferredSessionId)
        ? preferredSessionId
        : nextSessions[0]?.id || '';
      setActiveSessionId(nextSessionId);
      activeSessionIdRef.current = nextSessionId;
      if (nextSessionId) {
        await loadMessagesForSession(nextSessionId, agentId);
      } else {
        setMessages([WELCOME_MESSAGE]);
      }
    } catch (event) {
      if (activeAgentIdRef.current !== agentId) return;
      setError(`读取会话失败：${event.message}`);
      setMessages([WELCOME_MESSAGE]);
    } finally {
      if (activeAgentIdRef.current === agentId) {
        setSessionsLoading(false);
      }
    }
  }

  async function loadMessagesForSession(sessionId, agentId = activeAgentIdRef.current) {
    if (!sessionId) {
      setMessages([WELCOME_MESSAGE]);
      return;
    }
    const data = await loadSessionMessages(sessionId);
    if (agentId && activeAgentIdRef.current !== agentId) return;
    if (activeSessionIdRef.current && activeSessionIdRef.current !== sessionId) return;
    const nextMessages = (data.messages || []).map(normalizeChatMessage);
    setMessages(nextMessages.length ? nextMessages : [WELCOME_MESSAGE]);
  }

  async function createSession(agentId = activeAgentId) {
    const targetAgentId = typeof agentId === 'string' ? agentId : activeAgentIdRef.current;
    if (!targetAgentId) return null;
    setStatus('正在新建会话');
    setError('');
    try {
      const data = await createAgentSession(targetAgentId);
      if (activeAgentIdRef.current !== targetAgentId) return null;
      const session = data.session;
      setSessions((current) => [session, ...current]);
      setActiveSessionId(session.id);
      activeSessionIdRef.current = session.id;
      setMessages([WELCOME_MESSAGE]);
      setStatus('会话已创建');
      return session;
    } catch (event) {
      if (activeAgentIdRef.current !== targetAgentId) return null;
      setError(`新建会话失败：${event.message}`);
      setStatus('新建会话失败');
      throw event;
    }
  }

  async function selectSession(sessionId) {
    if (!sessionId || sessionId === activeSessionId) return;
    setActiveSessionId(sessionId);
    activeSessionIdRef.current = sessionId;
    await loadMessagesForSession(sessionId, activeAgentId);
  }

  async function deleteSession(sessionId) {
    if (!sessionId) return;
    setStatus('正在删除会话');
    setError('');
    try {
      await deleteAgentSession(sessionId);
      const nextSessions = sessions.filter((session) => session.id !== sessionId);
      setSessions(nextSessions);
      const nextSessionId = activeSessionId === sessionId ? nextSessions[0]?.id || '' : activeSessionId;
      setActiveSessionId(nextSessionId);
      activeSessionIdRef.current = nextSessionId;
      if (nextSessionId) {
        activeSessionIdRef.current = nextSessionId;
        await loadMessagesForSession(nextSessionId, activeAgentId);
      } else {
        setMessages([WELCOME_MESSAGE]);
      }
      setStatus('会话已删除');
    } catch (event) {
      setError(`删除会话失败：${event.message}`);
      setStatus('删除会话失败');
    }
  }

  function requestDeleteSession(sessionId) {
    const session = sessions.find((item) => item.id === sessionId);
    if (!session) return;
    setPendingDeleteSession(session);
  }

  async function confirmDeleteSession() {
    if (!pendingDeleteSession) return;
    const sessionId = pendingDeleteSession.id;
    setPendingDeleteSession(null);
    await deleteSession(sessionId);
  }

  async function createAgent({ name, description, packageIds, configs = {} }) {
    setStatus('正在创建智能体');
    setError('');
    try {
      const selectedPackageIds = packageIds?.length
        ? packageIds.filter((packageId) => packages.some((item) => item.package_id === packageId))
        : DEFAULT_PACKAGES.filter((packageId) => packages.some((item) => item.package_id === packageId));
      const payload = createDefaultAgentPayload(name, description, packages, selectedPackageIds, configs);
      const data = await api('/api/agents', { method: 'POST', body: JSON.stringify(payload) });
      setAgents((current) => [data.agent, ...current]);
      setActiveAgentId(data.agent.id);
      setAgentDetails(data.agent);
      setStatus('智能体已创建');
      return data.agent;
    } catch (event) {
      setError(`创建失败：${event.message}`);
      setStatus('创建失败');
      throw event;
    }
  }

  function requestDeleteAgent(agentId) {
    const target = agents.find((agent) => agent.id === agentId);
    if (!target) return;
    setPendingDeleteAgent(target);
  }

  async function confirmDeleteAgent() {
    if (!pendingDeleteAgent) return;
    const agentId = pendingDeleteAgent.id;
    setPendingDeleteAgent(null);
    setStatus('正在删除智能体');
    setError('');
    try {
      await api(`/api/agents/${agentId}`, { method: 'DELETE' });
      const nextAgents = agents.filter((agent) => agent.id !== agentId);
      setAgents(nextAgents);
      if (activeAgentId === agentId) {
        const nextActiveAgentId = nextAgents[0]?.id || '';
        setActiveAgentId(nextActiveAgentId);
        if (!nextActiveAgentId) {
          setAgentDetails(null);
          setResources([]);
          setCapabilities([]);
          setCapabilityCandidates([]);
          setCapabilityBindings({});
          setDiagnostics([]);
          setRuntimeStatus('ready');
          setSessions([]);
          setActiveSessionId('');
          setMessages([WELCOME_MESSAGE]);
        }
      }
      setStatus('智能体已删除');
    } catch (event) {
      setError(`删除失败：${event.message}`);
      setStatus('删除失败');
    }
  }

  async function updateAgent(agentId, payload) {
    if (!agentId) return;
    setStatus('正在保存智能体');
    setError('');
    try {
      const data = await updateAgentRequest(agentId, payload);
      setAgents((current) => current.map((agent) => (
        agent.id === data.agent.id ? { ...agent, ...data.agent } : agent
      )));
      setAgentDetails((current) => (current?.id === data.agent.id ? data.agent : current));
      setStatus('智能体已保存');
      return data.agent;
    } catch (event) {
      setError(`保存智能体失败：${event.message}`);
      setStatus('保存失败');
      throw event;
    }
  }

  async function updateAgentComposition(agent, { name, description, packageIds }) {
    if (!agent?.id) return null;
    const sourceAgent = agentDetails?.id === agent.id ? agentDetails : agent;
    const packageById = new Map(packages.map((pluginPackage) => [pluginPackage.package_id, pluginPackage]));
    const existingByPackage = new Map();
    for (const instance of sourceAgent.plugin_instances || []) {
      if (existingByPackage.has(instance.package_id)) {
        throw new Error(`该智能体包含多个 ${instance.package_id} 插件实例，广场组合编辑暂不支持多实例智能体，请在工作台逐个调整配置。`);
      }
      if (!existingByPackage.has(instance.package_id)) {
        existingByPackage.set(instance.package_id, instance);
      }
    }
    const selectedPackageIds = (packageIds || []).filter((packageId) => packageById.has(packageId));
    const pluginInstances = selectedPackageIds.map((packageId) => {
      const pluginPackage = packageById.get(packageId);
      const existing = existingByPackage.get(packageId);
      return {
        ...(existing?.instance_id ? { instance_id: existing.instance_id } : {}),
        package_id: packageId,
        package_version: existing?.package_version || pluginPackage?.version,
        display_name: existing?.display_name || pluginPackage?.name || packageId,
        config: existing?.config || {},
      };
    });
    const updated = await updateAgent(agent.id, {
      name,
      description,
      plugin_ids: selectedPackageIds,
      configs: Object.fromEntries(pluginInstances.map((instance) => [instance.package_id, instance.config])),
      plugin_instances: pluginInstances,
    });
    if (activeAgentId === agent.id) {
      await refreshAgentRuntime(agent.id);
    }
    return updated;
  }

  async function saveCapabilityBindings(nextPartialBindings) {
    if (!activeAgentId || !nextPartialBindings || !Object.keys(nextPartialBindings).length) return;
    const nextBindings = { ...capabilityBindings, ...nextPartialBindings };
    setStatus('正在保存能力绑定');
    setError('');
    try {
      const data = await updateAgentCapabilityBindings(activeAgentId, nextBindings);
      setCapabilityBindings(data.agent.capability_bindings || nextBindings);
      setAgentDetails(data.agent);
      setAgents((current) => current.map((agent) => (
        agent.id === data.agent.id ? { ...agent, ...data.agent } : agent
      )));
      await refreshAgentRuntime(activeAgentId);
      setStatus('能力绑定已保存');
    } catch (event) {
      setError(`保存能力绑定失败：${event.message}`);
      setStatus('保存失败');
      throw event;
    }
  }

  async function saveCapabilityBinding(capability, providerInstanceId) {
    if (!capability || !providerInstanceId) return;
    return saveCapabilityBindings({ [capability]: providerInstanceId });
  }

  async function savePluginConfig(instanceId, config) {
    const label = pluginInstanceLabel(agentDetails, instanceId);
    setStatus('正在保存插件配置');
    setError('');
    setToast({ message: `正在保存「${label}」配置`, variant: 'info' });
    try {
      const data = await api(`/api/plugin-instances/${instanceId}/config`, {
        method: 'PUT',
        body: JSON.stringify({ config }),
      });
      setAgentDetails((current) => replaceInstance(current, data.plugin_instance));
      setStatus('插件配置已保存');
      setToast({ message: `「${label}」配置已保存`, variant: 'success' });
      await refreshAgentRuntime();
    } catch (event) {
      setError(`保存失败：${event.message}`);
      setToast({ message: `「${label}」保存失败：${event.message}`, variant: 'error' });
      setStatus('保存失败');
    }
  }

  async function restartPluginInstance(instanceId) {
    const label = pluginInstanceLabel(agentDetails, instanceId);
    setStatus('正在重启插件实例');
    setError('');
    setToast({ message: `正在重启「${label}」`, variant: 'info' });
    try {
      const data = await api(`/api/plugin-instances/${instanceId}/restart`, { method: 'POST', body: JSON.stringify({}) });
      setAgentDetails((current) => replaceInstance(current, data.plugin_instance));
      setStatus('插件实例已重启');
      setToast({ message: `「${label}」已重启`, variant: 'success' });
      await refreshAgentRuntime();
    } catch (event) {
      setError(`重启失败：${event.message}`);
      setToast({ message: `「${label}」重启失败：${event.message}`, variant: 'error' });
      setStatus('重启失败');
    }
  }

  async function sendMessage(text) {
    if (!activeAgentId || !text.trim()) return;
    const runAgentId = activeAgentId;
    const session = activeSessionId ? { id: activeSessionId } : await createSession(runAgentId);
    if (!session?.id) return;
    if (activeAgentIdRef.current !== runAgentId) return;
    const runSessionId = session.id;
    const stamp = Date.now();
    const assistantId = `assistant-${stamp}`;
    const userMessage = { id: `user-${stamp}`, role: 'user', content: text.trim() };
    const assistantMessage = { id: assistantId, role: 'assistant', content: '', meta: { events: [], tool_calls: [] } };
    setActiveSessionId(runSessionId);
    activeSessionIdRef.current = runSessionId;
    setMessages((current) => [
      ...current.filter((message) => message.id !== 'welcome'),
      userMessage,
      assistantMessage,
    ]);
    setIsRunning(true);
    setStatus('智能体运行中');
    setError('');
    try {
      await streamAgentRun(runAgentId, runSessionId, text.trim(), (event) => {
        if (activeAgentIdRef.current !== runAgentId || activeSessionIdRef.current !== runSessionId) return;
        applyStreamEvent(assistantId, event);
      });
      if (activeAgentIdRef.current === runAgentId && activeSessionIdRef.current === runSessionId) {
        await refreshAgentSessions(runAgentId, runSessionId);
      }
    } catch (event) {
      if (activeAgentIdRef.current !== runAgentId || activeSessionIdRef.current !== runSessionId) return;
      setError(`运行失败：${event.message}`);
      setMessages((current) => current.map((message) => (
        message.id === assistantId
          ? { ...message, content: message.content || `运行失败：${event.message}` }
          : message
      )));
      setStatus('运行失败');
    } finally {
      if (activeAgentIdRef.current === runAgentId && activeSessionIdRef.current === runSessionId) {
        setIsRunning(false);
      }
    }
  }

  function applyStreamEvent(assistantId, event) {
    if (event.type === 'model_delta') {
      setMessages((current) => updateAssistantMessage(current, assistantId, (message) => ({
        ...message,
        content: `${message.content || ''}${event.payload?.delta || ''}`,
        meta: appendEvent(message.meta, event),
      })));
      setStatus('正在接收模型输出');
      return;
    }
    if (event.type === 'tool_call_started') {
      setMessages((current) => updateAssistantMessage(current, assistantId, (message) => ({
        ...message,
        meta: appendToolEvent(appendEvent(message.meta, event), event, 'running'),
      })));
      setStatus(`正在调用工具：${event.payload?.tool_name || ''}`);
      return;
    }
    if (event.type === 'tool_call_completed') {
      setMessages((current) => updateAssistantMessage(current, assistantId, (message) => ({
        ...message,
        meta: appendToolEvent(appendEvent(message.meta, event), event, event.payload?.ok === false ? 'failed' : 'completed'),
      })));
      setStatus('工具调用完成');
      return;
    }
    if (event.type === 'run_completed') {
      const result = event.payload || {};
      setMessages((current) => updateAssistantMessage(current, assistantId, (message) => ({
        ...message,
        content: result.answer || message.content || '没有返回内容',
        meta: { ...result, events: [...(message.meta?.events || []), event] },
      })));
      setStatus(result.stop_reason === 'error' ? '运行结束：有错误' : '运行完成');
      return;
    }
    if (event.type === 'run_failed') {
      const result = event.payload || {};
      setMessages((current) => updateAssistantMessage(current, assistantId, (message) => ({
        ...message,
        content: result.answer || message.content || '运行失败',
        meta: { ...result, events: [...(message.meta?.events || []), event] },
      })));
      setStatus('运行失败');
      return;
    }
    setMessages((current) => updateAssistantMessage(current, assistantId, (message) => ({
      ...message,
      meta: appendEvent(message.meta, event),
    })));
  }

  const activeAgent = useMemo(() => agents.find((agent) => agent.id === activeAgentId), [agents, activeAgentId]);
  const notification = error ? { message: error, variant: 'error' } : toast;

  return (
    <main className="app-shell">
      <header className="app-topbar">
        <div className="nav-brand">
          <Bot size={24} />
          <div>
            <strong>Plugin Agent</strong>
            <span>插件化智能体控制台</span>
          </div>
        </div>
        <nav className="nav-menu">
          <button className={view === 'square' ? 'nav-item active' : 'nav-item'} onClick={() => setView('square')}><Boxes size={17} /><span>智能体广场</span></button>
          <button className={view === 'workbench' ? 'nav-item active' : 'nav-item'} onClick={() => setView('workbench')}><MessageSquare size={17} /><span>智能体工作台</span></button>
          <button className={view === 'market' ? 'nav-item active' : 'nav-item'} onClick={() => setView('market')}><Store size={17} /><span>插件市场</span></button>
        </nav>
        <div className="topbar-meta">
        </div>
      </header>
      <NotificationToast
        message={notification?.message}
        variant={notification?.variant || 'info'}
        onClose={() => {
          if (error) {
            setError('');
          } else {
            setToast(null);
          }
        }}
      />

      <section className="app-main">
        {view === 'market' && <MarketPage packages={packages} apiBase={API_BASE} onMarketplaceChanged={refresh} />}
        {view === 'square' && (
          <AgentSquarePage
            agents={agents}
            activeAgentId={activeAgentId}
            setActiveAgentId={setActiveAgentId}
            setView={setView}
            createAgent={createAgent}
            updateAgent={updateAgentComposition}
            deleteAgent={requestDeleteAgent}
            packages={packages}
          />
        )}
        {view === 'workbench' && (
          <WorkbenchPage
            apiBase={API_BASE}
            status={status}
            agents={agents}
            activeAgent={activeAgent}
            activeAgentId={activeAgentId}
            setActiveAgentId={setActiveAgentId}
            agentDetails={agentDetails}
            resources={resources}
            capabilities={capabilities}
            capabilityCandidates={capabilityCandidates}
            capabilityBindings={capabilityBindings}
            diagnostics={diagnostics}
            runtimeStatus={runtimeStatus}
            packages={packages}
            updateAgent={updateAgent}
            saveCapabilityBinding={saveCapabilityBinding}
            saveCapabilityBindings={saveCapabilityBindings}
            savePluginConfig={savePluginConfig}
            restartPluginInstance={restartPluginInstance}
            sessions={sessions}
            activeSessionId={activeSessionId}
            sessionsLoading={sessionsLoading}
            createSession={createSession}
            selectSession={selectSession}
            deleteSession={requestDeleteSession}
            messages={messages}
            isRunning={isRunning}
            sendMessage={sendMessage}
          />
        )}
      </section>
      <ConfirmDialog
        open={Boolean(pendingDeleteAgent)}
        title="删除智能体"
        description={pendingDeleteAgent ? `确定删除「${pendingDeleteAgent.name}」？此操作会移除它的插件实例配置。` : ''}
        confirmLabel="删除"
        cancelLabel="取消"
        tone="danger"
        onConfirm={confirmDeleteAgent}
        onCancel={() => setPendingDeleteAgent(null)}
      />
      <ConfirmDialog
        open={Boolean(pendingDeleteSession)}
        title="删除历史对话"
        description={pendingDeleteSession ? `确定删除「${pendingDeleteSession.title || '新会话'}」？删除后无法恢复。` : ''}
        confirmLabel="删除"
        cancelLabel="取消"
        tone="danger"
        onConfirm={confirmDeleteSession}
        onCancel={() => setPendingDeleteSession(null)}
      />
    </main>
  );
}

function replaceInstance(agentDetails, pluginInstance) {
  if (!agentDetails) return agentDetails;
  return {
    ...agentDetails,
    plugin_instances: (agentDetails.plugin_instances || []).map((instance) => (
      instance.instance_id === pluginInstance.instance_id ? pluginInstance : instance
    )),
  };
}

function pluginInstanceLabel(agentDetails, instanceId) {
  const instance = (agentDetails?.plugin_instances || []).find((item) => item.instance_id === instanceId);
  return instance?.display_name || instance?.package_id || instanceId || '插件';
}

function normalizeChatMessage(message) {
  return {
    id: message.message_id,
    role: message.role,
    content: message.content,
    meta: message.metadata || {},
  };
}

function updateAssistantMessage(messages, assistantId, updater) {
  return messages.map((message) => (message.id === assistantId ? updater(message) : message));
}

function appendEvent(meta = {}, event) {
  return { ...meta, events: [...(meta.events || []), event] };
}

function appendToolEvent(meta = {}, event, status) {
  const payload = event.payload || {};
  const callId = payload.tool_call_id || `${payload.tool_name}-${meta.tool_calls?.length || 0}`;
  const nextCall = {
    tool_call_id: callId,
    tool_id: payload.tool_name,
    arguments: payload.input,
    result: payload.result,
    status,
  };
  const existing = meta.tool_calls || [];
  const index = existing.findIndex((call) => call.tool_call_id === callId);
  const toolCalls = index >= 0
    ? existing.map((call, itemIndex) => (itemIndex === index ? { ...call, ...nextCall } : call))
    : [...existing, nextCall];
  return { ...meta, tool_calls: toolCalls };
}
