import { useMemo, useState } from 'react';
import { Bot, Edit3, MessageSquare, MoreVertical, Plus, Search, Trash2 } from 'lucide-react';
import { AgentCreateDialog } from '../components/AgentCreateDialog.jsx';

export function AgentSquarePage({ agents, activeAgentId, setActiveAgentId, setView, createAgent, updateAgent, deleteAgent, packages }) {
  const [createOpen, setCreateOpen] = useState(false);
  const [editingAgent, setEditingAgent] = useState(null);
  const [menuAgentId, setMenuAgentId] = useState('');
  const [query, setQuery] = useState('');
  const filteredAgents = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    if (!normalizedQuery) return agents;
    return agents.filter((agent) => [
      agent.name,
      agent.description,
      agent.id,
      ...(agent.plugin_ids || []),
      ...(agent.plugin_instances || []).map((instance) => instance.display_name || instance.package_id),
    ].join(' ').toLowerCase().includes(normalizedQuery));
  }, [agents, query]);

  return (
    <section className="page-panel agent-square-page">
      <header className="market-topbar agent-square-topbar">
        <div className="market-tabs" aria-label="智能体视图">
          <button className="market-tab active">
            智能体
            <span>{agents.length}</span>
          </button>
        </div>
        <button className="primary-button page-action" onClick={() => setCreateOpen(true)}><Plus size={15} />新建智能体</button>
      </header>

      <div className="market-content">
        <section className="market-hero agent-square-hero">
          <h1>智能体</h1>
          <p>选择一个智能体进入工作台，或使用插件组合创建新的 Agent 运行环境。</p>
          <label className="agent-square-search">
            <Search size={16} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索智能体" />
          </label>
        </section>

        <section className="market-results agent-square-results">
          <div className="market-section-head">
            <div>
              <strong>已创建智能体</strong>
              <span>{filteredAgents.length} / {agents.length} 个智能体{query.trim() ? ` · ${query.trim()}` : ''}</span>
            </div>
          </div>

          <div className="agent-grid">
          {filteredAgents.map((agent) => (
            <article
              key={agent.id}
              className="agent-card"
            >
              <button
                className="agent-open-button"
                onClick={() => {
                  setActiveAgentId(agent.id);
                  setView('workbench');
                }}
              >
                <span className="agent-card-icon"><Bot size={21} /></span>
                <span className="agent-card-main">
                  <span className="agent-card-title">
                    <strong>{agent.name}</strong>
                    <span>{agent.plugin_instances?.length || agent.plugin_ids?.length || 0} 个插件</span>
                  </span>
                  <p>{agent.description || '暂无描述'}</p>
                  <span className="agent-card-meta">
                    <code>{agent.id}</code>
                  </span>
                </span>
              </button>
              <button
                className="agent-more-button"
                onClick={() => setMenuAgentId((current) => (current === agent.id ? '' : agent.id))}
                title="更多操作"
                aria-label={`${agent.name} 更多操作`}
                aria-expanded={menuAgentId === agent.id}
              >
                <MoreVertical size={17} />
              </button>
              {menuAgentId === agent.id && (
                <div className="agent-card-menu" role="menu">
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      setMenuAgentId('');
                      setActiveAgentId(agent.id);
                      setView('workbench');
                    }}
                  >
                    <MessageSquare size={14} />对话
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      setMenuAgentId('');
                      setEditingAgent(agent);
                    }}
                  >
                    <Edit3 size={14} />编辑
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    className="danger"
                    onClick={() => {
                      setMenuAgentId('');
                      deleteAgent(agent.id);
                    }}
                  >
                    <Trash2 size={14} />删除
                  </button>
                </div>
              )}
            </article>
          ))}
            {!filteredAgents.length && (
              <div className="market-empty">
                <Bot size={24} />
                <strong>{agents.length ? '没有匹配的智能体' : '还没有智能体'}</strong>
                <span>{agents.length ? '换个关键词再试试。' : `已发现 ${packages.length} 个插件包，可以先新建一个智能体。`}</span>
              </div>
            )}
          </div>
        </section>
      </div>
      <AgentCreateDialog
        open={createOpen}
        packages={packages}
        onCreate={createAgent}
        onCancel={() => setCreateOpen(false)}
      />
      <AgentCreateDialog
        open={Boolean(editingAgent)}
        mode="edit"
        agent={editingAgent}
        packages={packages}
        onCreate={(payload) => updateAgent(editingAgent, payload)}
        onCancel={() => setEditingAgent(null)}
      />
    </section>
  );
}
