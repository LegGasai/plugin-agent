import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Bot, CheckCircle2, Database, Gauge, Link2, Save, Settings, X } from 'lucide-react';
import { resourceLabel, stripRedactedSecrets } from '../lib/plugins.js';
import { PluginConfigPanel } from './PluginConfigPanel.jsx';

export function AgentSidebar({
  agents,
  activeAgentId,
  setActiveAgentId,
  agentDetails,
  resources,
  capabilities,
  capabilityCandidates,
  capabilityBindings,
  diagnostics,
  runtimeStatus,
  packages,
  updateAgent,
  saveCapabilityBinding,
  saveCapabilityBindings,
  savePluginConfig,
  restartPluginInstance,
}) {
  const [draftName, setDraftName] = useState('');
  const [draftDescription, setDraftDescription] = useState('');
  const [isSavingAgent, setIsSavingAgent] = useState(false);

  useEffect(() => {
    setDraftName(agentDetails?.name || '');
    setDraftDescription(agentDetails?.description || '');
    setIsSavingAgent(false);
  }, [agentDetails?.id, agentDetails?.name, agentDetails?.description]);

  const isAgentDirty = useMemo(() => (
    Boolean(agentDetails)
    && (draftName.trim() !== (agentDetails.name || '') || draftDescription.trim() !== (agentDetails.description || ''))
  ), [agentDetails, draftDescription, draftName]);

  async function handleAgentSubmit(event) {
    event.preventDefault();
    if (!agentDetails || !draftName.trim() || !isAgentDirty) return;
    setIsSavingAgent(true);
    try {
      await updateAgent(agentDetails.id, {
        name: draftName.trim(),
        description: draftDescription.trim(),
      });
    } finally {
      setIsSavingAgent(false);
    }
  }

  return (
    <section className="sidebar-content">
      <div className="agent-config-overview">
        <div className="sidebar-section compact agent-picker-section">
          <div className="section-title"><Bot size={16} />智能体</div>
          <label className="agent-select-wrap">
            <select value={activeAgentId} onChange={(event) => setActiveAgentId(event.target.value)} aria-label="选择智能体">
              <option value="">选择智能体</option>
              {agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
            </select>
          </label>
          {agentDetails ? (
            <form className="agent-edit-form" onSubmit={handleAgentSubmit}>
              <label className="agent-field">
                <span>名称</span>
                <input
                  value={draftName}
                  onChange={(event) => setDraftName(event.target.value)}
                  placeholder="智能体名称"
                  maxLength={64}
                />
              </label>
              <label className="agent-field">
                <span>描述</span>
                <textarea
                  value={draftDescription}
                  onChange={(event) => setDraftDescription(event.target.value)}
                  placeholder="描述这个智能体的用途"
                  rows={2}
                  maxLength={180}
                />
              </label>
              <div className="agent-edit-actions">
                <span>当前配置对象</span>
                <button className="mini-button primary-mini" type="submit" disabled={!isAgentDirty || !draftName.trim() || isSavingAgent}>
                  <Save size={13} />
                  {isSavingAgent ? '保存中' : '保存'}
                </button>
              </div>
            </form>
          ) : (
            <p className="empty">还没有智能体。可以先创建默认智能体。</p>
          )}
        </div>

        <RuntimeOverview
          agentDetails={agentDetails}
          resources={resources}
          capabilities={capabilities}
          capabilityCandidates={capabilityCandidates}
          capabilityBindings={capabilityBindings}
          status={runtimeStatus}
          diagnostics={diagnostics}
          packages={packages}
          onBindCapability={saveCapabilityBinding}
          onBindCapabilities={saveCapabilityBindings}
        />
      </div>

      <div className="sidebar-section plugin-config-section">
        <div className="section-title section-title-row">
          <span><Settings size={16} />插件配置</span>
          <small>{agentDetails?.plugin_instances?.length || 0} 个插件</small>
        </div>
        <div className="plugin-config-list">
          {(agentDetails?.plugin_instances || []).map((instance) => (
            <PluginConfigPanel
              key={instance.instance_id}
              instance={instance}
              pluginPackage={findPackageForInstance(packages, instance)}
              onSave={(config) => savePluginConfig(instance.instance_id, stripRedactedSecrets(config))}
              onRestart={() => restartPluginInstance(instance.instance_id)}
            />
          ))}
          {!agentDetails?.plugin_instances?.length && <p className="empty">选择或创建智能体后，可在这里编辑每个插件的配置。</p>}
        </div>
      </div>
    </section>
  );
}

function findPackageForInstance(packages, instance) {
  const candidates = packages.filter((item) => item.package_id === instance.package_id);
  if (!candidates.length) return null;
  const pinned = instance.package_version || instance.version;
  if (pinned) {
    const exact = candidates.find((item) => item.version === pinned);
    if (exact) return exact;
  }
  return candidates
    .slice()
    .sort((left, right) => String(right.version || '').localeCompare(String(left.version || ''), undefined, { numeric: true }))[0];
}

function RuntimeOverview({
  agentDetails,
  resources,
  capabilities,
  capabilityCandidates = [],
  capabilityBindings = {},
  status,
  diagnostics = [],
  packages = [],
  onBindCapability,
  onBindCapabilities,
}) {
  const bindableCapabilities = capabilityCandidates.filter((item) => (item.candidates || []).length > 1);
  const conflicts = bindableCapabilities.filter((item) => item.status === 'conflict');
  const [draftBindings, setDraftBindings] = useState({});
  const [bindingDialogOpen, setBindingDialogOpen] = useState(false);
  const [isSavingBindings, setIsSavingBindings] = useState(false);
  useEffect(() => {
    const nextDrafts = {};
    bindableCapabilities.forEach((item) => {
      const candidateIds = (item.candidates || []).map((candidate) => candidate.provider_instance_id);
      const currentBinding = capabilityBindings[item.capability];
      nextDrafts[item.capability] = candidateIds.includes(currentBinding) ? currentBinding : candidateIds[0] || '';
    });
    setDraftBindings(nextDrafts);
  }, [capabilityBindings, bindableCapabilities.map((item) => `${item.capability}:${(item.candidates || []).map((candidate) => candidate.provider_instance_id).join(',')}`).join('|')]);
  const selectedBindingCount = bindableCapabilities.filter((item) => draftBindings[item.capability]).length;
  const isReady = status === 'ready';
  const title = status === 'failed' ? '运行时失败' : status === 'degraded' ? '运行时降级' : '运行时就绪';
  const resourceStats = resourceTypeStats(resources).slice(0, 6);
  const maxResourceCount = Math.max(...resourceStats.map((item) => item.count), 1);

  async function saveBindings(event) {
    event.preventDefault();
    if (!bindableCapabilities.length || selectedBindingCount !== bindableCapabilities.length) return;
    setIsSavingBindings(true);
    try {
      const nextBindings = {};
      bindableCapabilities.forEach((item) => {
        nextBindings[item.capability] = draftBindings[item.capability];
      });
      if (onBindCapabilities) {
        await onBindCapabilities(nextBindings);
      } else {
        await Promise.all(bindableCapabilities.map((item) => onBindCapability?.(item.capability, draftBindings[item.capability])));
      }
      setBindingDialogOpen(false);
    } catch {
      // App-level status already shows the failure; keep the dialog open with the user's selections.
    } finally {
      setIsSavingBindings(false);
    }
  }

  return (
    <div className={`sidebar-section runtime-overview ${status || 'ready'}`}>
      <div className="overview-head">
        <div className="section-title"><Gauge size={16} />运行概览</div>
        <span className="runtime-status">
          {isReady ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
          {title}
        </span>
      </div>
      <div className="metrics compact-metrics">
        <div title="当前智能体装配的插件数量"><strong>{agentDetails?.plugin_instances?.length || 0}</strong><span>插件</span></div>
        <div title="插件暴露给 Agent 发现和使用的对象数量"><strong>{resources.length}</strong><span>资源</span></div>
        <div title="插件注册到内核、可被调用的接口数量"><strong>{capabilities.length}</strong><span>能力</span></div>
      </div>
      <div className="resource-summary">
        <div className="resource-summary-title"><Database size={14} />资源分布</div>
        <div className="resource-stat-list">
          {resourceStats.map((item) => (
            <div className="resource-stat" key={item.label}>
              <span>{item.label}</span>
              <strong>{item.count}</strong>
              <i style={{ '--fill': `${Math.max((item.count / maxResourceCount) * 100, 10)}%` }} />
            </div>
          ))}
          {!resources.length && <span className="empty-resource">暂无资源</span>}
        </div>
      </div>
      <div className="runtime-footnote">
        <span>能力路由</span>
        <strong>{capabilities.length ? `${capabilities.length} 个接口已注册` : '暂无接口'}</strong>
        <small>资源用于发现，能力用于调用。</small>
      </div>
      {diagnostics.length ? (
        <div className="diagnostic-panel">
          <div className="diagnostic-panel-head">
            <span><AlertTriangle size={13} />检测失败</span>
            <span className="diagnostic-head-actions">
              <small>{diagnostics.length} 项</small>
              {bindableCapabilities.length ? (
                <button className="diagnostic-bind-button" type="button" onClick={() => setBindingDialogOpen(true)}>
                  <Link2 size={12} />
                  {conflicts.length ? `绑定 ${conflicts.length}` : '修改绑定'}
                </button>
              ) : null}
            </span>
          </div>
          <div className="diagnostic-list">
            {diagnostics.map((diagnostic, index) => (
              <div className="diagnostic-item" key={`${diagnostic.code}-${diagnostic.capability || index}`}>
                <div className="diagnostic-title">
                  <strong title={diagnostic.capability || diagnostic.code}>{diagnostic.capability || diagnostic.code}</strong>
                  {diagnostic.capability && diagnostic.code ? <em>{diagnostic.code}</em> : null}
                </div>
                <span title={diagnostic.message}>{diagnostic.message}</span>
              </div>
            ))}
          </div>
        </div>
      ) : (
        bindableCapabilities.length ? (
          <button className={conflicts.length ? 'binding-inline-alert' : 'binding-inline-alert neutral'} type="button" onClick={() => setBindingDialogOpen(true)}>
            <span><Link2 size={13} />{conflicts.length ? `${conflicts.length} 个能力待指定 provider` : `${bindableCapabilities.length} 个能力已配置 provider 路由`}</span>
            <strong>{conflicts.length ? '绑定' : '调整'}</strong>
          </button>
        ) : (
          <p className="empty overview-empty">依赖解析正常，能力路由已建立。</p>
        )
      )}
      <CapabilityBindingDialog
        open={bindingDialogOpen}
        capabilities={bindableCapabilities}
        agentDetails={agentDetails}
        packages={packages}
        draftBindings={draftBindings}
        setDraftBindings={setDraftBindings}
        selectedCount={selectedBindingCount}
        saving={isSavingBindings}
        onCancel={() => setBindingDialogOpen(false)}
        onSave={saveBindings}
      />
    </div>
  );
}

function CapabilityBindingDialog({
  open,
  capabilities,
  agentDetails,
  packages,
  draftBindings,
  setDraftBindings,
  selectedCount,
  saving,
  onCancel,
  onSave,
}) {
  if (!open) return null;

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={onCancel}>
      <section className="capability-binding-dialog" role="dialog" aria-modal="true" aria-labelledby="capability-binding-title" onMouseDown={(event) => event.stopPropagation()}>
        <button className="dialog-close-button" onClick={onCancel} aria-label="关闭弹窗">
          <X size={16} />
        </button>
        <header className="capability-binding-head">
          <div className="dialog-icon danger"><Link2 size={20} /></div>
          <div>
            <h2 id="capability-binding-title">配置能力绑定</h2>
            <p>多个插件提供同名能力时，需要为 Agent 指定实际调用的 provider。</p>
          </div>
        </header>

        <form className="capability-binding-form" onSubmit={onSave}>
          <div className="capability-binding-toolbar">
            <strong>{selectedCount} / {capabilities.length} 个已选择</strong>
            <span>建议优先选择当前模型、工具链或上下文插件中你准备启用的实例。</span>
          </div>

          <div className="capability-binding-list">
            {capabilities.map((item) => (
              <CapabilityBindingRow
                key={item.capability}
                item={item}
                value={draftBindings[item.capability] || ''}
                agentDetails={agentDetails}
                packages={packages}
                onChange={(providerInstanceId) => setDraftBindings((current) => ({ ...current, [item.capability]: providerInstanceId }))}
              />
            ))}
          </div>

          <div className="dialog-actions capability-binding-actions">
            <button type="button" className="dialog-cancel-button" onClick={onCancel}>取消</button>
            <button type="submit" className="dialog-confirm-button success" disabled={saving || selectedCount !== capabilities.length}>
              {saving ? '保存中' : '保存绑定'}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

function CapabilityBindingRow({ item, value, agentDetails, packages, onChange }) {
  return (
    <div className="capability-binding-row">
      <span className="capability-binding-copy">
        <strong title={item.capability}>{item.capability}</strong>
        <small>{item.candidates?.length || 0} 个候选 provider</small>
      </span>
      <span className="capability-provider-options">
        {(item.candidates || []).map((candidate) => (
          <label className={value === candidate.provider_instance_id ? 'capability-provider-option selected' : 'capability-provider-option'} key={candidate.provider_instance_id}>
            <input
              type="radio"
              name={`capability-${item.capability}`}
              checked={value === candidate.provider_instance_id}
              onChange={() => onChange(candidate.provider_instance_id)}
            />
            <span>
              <strong>{providerDisplayName(candidate, agentDetails, packages)}</strong>
              <code>{candidate.provider_instance_id}</code>
            </span>
          </label>
        ))}
      </span>
    </div>
  );
}

function providerDisplayName(candidate, agentDetails, packages) {
  const instance = (agentDetails?.plugin_instances || []).find((item) => item.instance_id === candidate.provider_instance_id);
  const pluginPackage = packages.find((item) => item.package_id === candidate.provider_plugin_id);
  return instance?.display_name || pluginPackage?.name || candidate.provider_plugin_id;
}

function resourceTypeStats(resources) {
  const counts = new Map();
  resources.forEach((resource) => {
    const label = resourceLabel(resource.kind);
    counts.set(label, (counts.get(label) || 0) + 1);
  });
  return Array.from(counts.entries())
    .map(([label, count]) => ({ label, count }))
    .sort((left, right) => right.count - left.count || left.label.localeCompare(right.label, 'zh-Hans-CN'));
}
