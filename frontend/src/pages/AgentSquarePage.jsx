import { useState } from 'react';
import { Bot, Plus, Trash2 } from 'lucide-react';
import { AgentCreateDialog } from '../components/AgentCreateDialog.jsx';

export function AgentSquarePage({ agents, activeAgentId, setActiveAgentId, setView, createAgent, deleteAgent, packages }) {
  const [createOpen, setCreateOpen] = useState(false);
  return (
    <section className="page-panel">
      <header className="page-header">
        <div>
          <span className="eyebrow">智能体广场</span>
          <h1>已创建智能体</h1>
          <p>选择一个智能体进入工作台，或使用插件组合创建一个新的智能体。</p>
        </div>
        <button className="primary-button page-action" onClick={() => setCreateOpen(true)}><Plus size={15} />新建智能体</button>
      </header>
      <div className="page-body single-column">
        <div className="agent-grid">
          {agents.map((agent) => (
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
                <Bot size={18} />
                <strong>{agent.name}</strong>
                <span>{agent.description || '暂无描述'}</span>
                <small>{agent.plugin_instances?.length || agent.plugin_ids?.length || 0} 个插件</small>
              </button>
              <button className="agent-delete-button" onClick={() => deleteAgent(agent.id)} title="删除智能体" aria-label={`删除智能体 ${agent.name}`}>
                <Trash2 size={15} />
              </button>
            </article>
          ))}
          {!agents.length && (
            <div className="page-empty">
              当前还没有智能体。已发现 {packages.length} 个插件包，可以先新建一个智能体。
            </div>
          )}
        </div>
      </div>
      <AgentCreateDialog
        open={createOpen}
        packages={packages}
        onCreate={createAgent}
        onCancel={() => setCreateOpen(false)}
      />
    </section>
  );
}
